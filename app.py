import os
import shutil
import uuid
import json
import zipfile
import logging
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, send_file, abort, after_this_request
import git  # Import GitPython
from cookiecutter.main import cookiecutter
from cookiecutter.exceptions import CookiecutterException

# --- Configuration ---
TEMP_DIR = Path("tmp")
OUTPUT_DIR = Path("output")
MAX_AGE_TEMP_FILES = timedelta(minutes=60)  # Cleanup files older than 60 mins

# Ensure temp and output directories exist
TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# --- In-memory store for template details ---
# WARNING: Not suitable for production with multiple workers.
# Use Redis, DB, etc. for a robust solution.
template_store = {}  # { template_id: {"tempdir": Path, "expires": datetime, "root_tempdir": Path} }

# --- Flask App Initialization ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)  # For potential future session use

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)


# --- Helper Functions ---


def cleanup_old_files():
    """Removes expired temporary directories and store entries."""
    now = datetime.now()
    expired_ids = [
        tid
        for tid, data in list(template_store.items())  # Iterate over a copy
        if data.get("expires") and data["expires"] < now
    ]
    for tid in expired_ids:
        logging.info(f"Checking expiration for template_id: {tid}")
        template_info = template_store.get(tid)
        if not template_info:  # Should not happen if iterating over copy, but safety check
            continue

        root_tempdir_path = template_info.get("root_tempdir")
        output_dir_path = OUTPUT_DIR / tid

        if root_tempdir_path and root_tempdir_path.exists():
            logging.info(f"Cleaning up expired temp directory: {root_tempdir_path}")
            try:
                shutil.rmtree(root_tempdir_path)
            except OSError as e:
                logging.error(f"Error removing temp directory {root_tempdir_path}: {e}")

        if output_dir_path.exists():
            logging.info(f"Cleaning up expired output directory: {output_dir_path}")
            try:
                shutil.rmtree(output_dir_path)
            except OSError as e:
                logging.error(f"Error removing output directory {output_dir_path}: {e}")

        # Finally, remove from store
        if tid in template_store:
            del template_store[tid]
            logging.info(f"Removed expired entry from store: {tid}")


def clone_repo(repo_url: str, target_dir: Path) -> None:
    """Clones a git repository to the target directory."""
    try:
        logging.info(f"Cloning {repo_url} to {target_dir}")
        git.Repo.clone_from(repo_url, target_dir, depth=1)
        logging.info(f"Successfully cloned {repo_url}")
    except git.GitCommandError as e:
        logging.error(f"Git clone failed for {repo_url}: {e}")
        raise ValueError(f"Failed to clone repository: {e.stderr}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during clone: {e}")
        raise ValueError("An unexpected error occurred while cloning.")


def copy_path(source_path_str: str, target_dir: Path) -> None:
    """Copies a local directory to the target directory."""
    source_path = Path(source_path_str)
    # Basic security check: Ensure it's an absolute path and exists
    if not source_path.is_absolute():
        raise ValueError("Local path must be absolute.")
    if not source_path.is_dir():
        msg = f"Local path '{source_path}' is not a valid directory."
        raise ValueError(msg)

    try:
        logging.info(f"Copying {source_path} to {target_dir}")
        # Ensure the target directory exists before copytree
        target_dir.mkdir(parents=True, exist_ok=True)
        # Copy contents into the target directory
        for item in source_path.iterdir():
            target_item = target_dir / item.name
            if item.is_dir():
                shutil.copytree(item, target_item, symlinks=False, ignore=None)
            else:
                shutil.copy2(item, target_item)
        logging.info(f"Successfully copied {source_path}")
    except OSError as e:
        logging.error(f"Directory copy failed for {source_path}: {e}")
        raise ValueError(f"Failed to copy local path: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during copy: {e}")
        raise ValueError("An unexpected error occurred while copying.")


def parse_cookiecutter_json(template_dir: Path) -> tuple[list, Path]:
    """Parses cookiecutter.json and returns a list of field definitions
       and the potentially adjusted template directory path."""
    # Find cookiecutter.json potentially within a subdirectory (common case)
    json_path = None
    effective_template_dir = template_dir
    if (template_dir / "cookiecutter.json").is_file():
        json_path = template_dir / "cookiecutter.json"
    else:
        # Check one level deeper
        possible_subdirs = [d for d in template_dir.iterdir() if d.is_dir()]
        if len(possible_subdirs) == 1:
            subdir_json_path = possible_subdirs[0] / "cookiecutter.json"
            if subdir_json_path.is_file():
                 effective_template_dir = possible_subdirs[0] # Adjust the effective dir
                 json_path = subdir_json_path

    if not json_path or not json_path.is_file():
        raise FileNotFoundError(
            "cookiecutter.json not found in the template root "
            "or its immediate subdirectory."
        )

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in cookiecutter.json: {e}")

    fields = []
    for name, default_value in data.items():
        # Skip private variables (starting with _)
        if name.startswith('_'):
            continue

        # Basic type inference
        field_type = "string"
        options = None
        help_text = None

        # Treat list as select choices
        if isinstance(default_value, list):
            field_type = "select"
            options = default_value
            default_value = options[0] if options else ""
        elif isinstance(default_value, bool):
            field_type = "boolean"
        elif isinstance(default_value, int):
            field_type = "integer"

        # Generic help text
        help_text = help_text or f"Enter value for {name}"

        # Don't add fields whose defaults look like template variables needing rendering
        # These should be handled internally by cookiecutter based on other context.
        is_templated_default = isinstance(default_value, str) and \
                                 "{{" in default_value and "}}" in default_value

        if not is_templated_default:
            fields.append({
                "name": name,
                "type": field_type,
                "default": default_value,
                "options": options,
                "help_text": help_text
            })

    return fields, effective_template_dir


def zip_directory(source_dir: Path, target_zip_path: Path):
    """Creates a zip archive from a source directory."""
    if not source_dir.is_dir():
        raise ValueError(f"Source for zipping is not a directory: {source_dir}")

    logging.info(f"Zipping directory {source_dir} to {target_zip_path}")
    try:
        with zipfile.ZipFile(target_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(source_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(source_dir)
                    zipf.write(file_path, arcname)
        logging.info(f"Successfully created zip file: {target_zip_path}")
    except Exception as e:
        logging.error(f"Failed to create zip file: {e}", exc_info=True)
        if target_zip_path.exists():
            target_zip_path.unlink(missing_ok=True)
        raise IOError(f"Failed to create zip archive: {e}")


# --- Routes ---


@app.route("/")
def index():
    """Renders the main page with the template source input form."""
    return render_template("index.html")


@app.route("/load", methods=["POST"])
def load_template():
    """Loads template source, parses cookiecutter.json, returns fields."""
    cleanup_old_files()

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 415

    data = request.get_json()
    source = data.get("source")

    if not source:
        return jsonify({"error": "Missing 'source' in request body"}), 400

    source = source.strip()
    is_url = source.startswith(("http://", "https://"))
    is_path = Path(source).is_absolute()

    if not is_url and not is_path:
        err_msg = "Source must be a valid HTTPS URL or an absolute server path."
        return jsonify({"error": err_msg}), 400

    template_id = str(uuid.uuid4())
    # This is the root dir where clone/copy happens
    root_temp_dir_path = TEMP_DIR / template_id

    try:
        if is_url:
            if not source.startswith("https://"):
                err_msg = "Only HTTPS URLs are supported."
                return jsonify({"error": err_msg}), 400
            clone_repo(source, root_temp_dir_path)
        else:
            copy_path(source, root_temp_dir_path)

        fields, effective_template_dir = parse_cookiecutter_json(root_temp_dir_path)

        expiration_time = datetime.now() + MAX_AGE_TEMP_FILES
        template_store[template_id] = {
            "tempdir": effective_template_dir,  # Dir containing cookiecutter.json
            "expires": expiration_time,
            "root_tempdir": root_temp_dir_path,  # Dir for cleanup
        }
        logging.info(f"Stored template info for id: {template_id}, path: {effective_template_dir}")

        return jsonify({"fields": fields, "template_id": template_id})

    except (ValueError, FileNotFoundError, git.GitCommandError) as e:
        logging.warning(f"Failed to load template '{source}': {e}")
        if root_temp_dir_path.exists():
            shutil.rmtree(root_temp_dir_path, ignore_errors=True)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logging.error(f"Unexpected error loading template '{source}': {e}", exc_info=True)
        if root_temp_dir_path.exists():
            shutil.rmtree(root_temp_dir_path, ignore_errors=True)
        abort(500, description="Internal error loading template.")


@app.route("/generate", methods=["POST"])
def generate_project():
    """Generates project using cookiecutter, zips it, and returns for download."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 415

    data = request.get_json()
    template_id = data.get("template_id")
    context = data.get("context")

    if not template_id or not isinstance(context, dict):
        return jsonify({"error": "Missing or invalid 'template_id' or 'context'"}), 400

    template_info = template_store.get(template_id)
    if not template_info:
        return jsonify({"error": "Template ID not found or expired. Please load again."}), 404

    template_dir = template_info["tempdir"]
    root_temp_dir = template_info.get("root_tempdir", template_dir)
    # Create a unique output subdir based on template_id
    output_parent_dir = OUTPUT_DIR / template_id
    final_zip_path = None  # Define before try block

    # Ensure output parent directory exists
    output_parent_dir.mkdir(exist_ok=True)

    try:
        # Run Cookiecutter
        logging.info(f"Generating project from template {template_dir} into {output_parent_dir}")
        # output_dir specifies WHERE the generated project dir should be created
        generated_project_path_str = cookiecutter(
            template=str(template_dir), no_input=True, extra_context=context, output_dir=str(output_parent_dir)
        )
        logging.info(f"Cookiecutter successful. Project generated at: {generated_project_path_str}")
        generated_project_path = Path(generated_project_path_str)

        if not generated_project_path.is_dir():
            raise IOError(f"Cookiecutter reported success, but generated path is not a directory: {generated_project_path}")

        # Use the actual generated directory name for the zip file
        zip_file_name = f"{generated_project_path.name}.zip"
        final_zip_path = output_parent_dir / zip_file_name  # Path for the zip

        # Zip the generated project directory
        zip_directory(generated_project_path, final_zip_path)

        # Schedule cleanup after the request is finished
        @after_this_request
        def cleanup(response):
            logging.info(f"Scheduling cleanup for temp: {root_temp_dir} and output: {output_parent_dir}")
            try:
                if root_temp_dir.exists():
                    shutil.rmtree(root_temp_dir, ignore_errors=True)
                    logging.info(f"Cleaned up temp directory: {root_temp_dir}")
                if output_parent_dir.exists():
                    # Clean up the entire output structure for this ID (incl. zip)
                    shutil.rmtree(output_parent_dir, ignore_errors=True)
                    logging.info(f"Cleaned up output directory: {output_parent_dir}")
            except Exception as e:
                logging.error(f"Error during post-request cleanup: {e}", exc_info=True)
            # Remove from store regardless
            if template_id in template_store:
                del template_store[template_id]
                logging.info(f"Removed ID {template_id} from store after request.")
            return response

        # Send the zip file
        logging.info(f"Sending zip file: {final_zip_path} as {zip_file_name}")
        return send_file(final_zip_path, mimetype="application/zip", as_attachment=True, download_name=zip_file_name)

    except (CookiecutterException, ValueError, IOError, OSError) as e:
        logging.error(f"Error during project generation or zipping: {e}", exc_info=True)
        # Clean up output dir in case of failure
        if output_parent_dir.exists():
            shutil.rmtree(output_parent_dir, ignore_errors=True)
        # Also clean up the temp dir
        if root_temp_dir.exists():
            shutil.rmtree(root_temp_dir, ignore_errors=True)
        # Remove from store
        if template_id in template_store:
            del template_store[template_id]
        return jsonify({"error": f"Generation failed: {e}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error during generation: {e}", exc_info=True)
        if output_parent_dir.exists():
            shutil.rmtree(output_parent_dir, ignore_errors=True)
        if root_temp_dir.exists():
            shutil.rmtree(root_temp_dir, ignore_errors=True)
        if template_id in template_store:
            del template_store[template_id]
        abort(500, description="An unexpected internal error occurred during generation.")


@app.errorhandler(404)
def page_not_found(e):
    """Custom 404 error handler."""
    return render_template("error.html", error_code=404, error_message="Page Not Found"), 404


@app.errorhandler(500)
def internal_server_error(e):
    """Custom 500 error handler."""
    original_exception = getattr(e, "original_exception", None)
    log_message = f"Internal Server Error: {e}"
    if original_exception:
        log_message += f" | Original Exception: {original_exception}"

    logging.error(log_message, exc_info=True if not original_exception else original_exception)

    error_message = getattr(e, "description", "An unexpected error occurred.")

    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        response = jsonify(error=error_message)
        response.status_code = 500
        return response

    return render_template("error.html", error_code=500, error_message=error_message), 500


# --- Main Execution ---


if __name__ == "__main__":
    # Note: Use 'flask run' for development
    app.run(debug=True)
