# cookieoven

A minimal Flask web application to generate projects from Cookiecutter templates.

## Prerequisites

- Python 3.10 or higher
- `pip` and `venv` (usually included with Python)
- `git` (must be installed and available in your system's PATH if you want to use Git URLs as template sources)

## Local Setup & Running

1.  **Clone the Repository (if applicable)**

    ```bash
    git clone <repository-url>
    cd cookiecutter-webapp
    ```

2.  **Create and Activate a Virtual Environment**

    *   On macOS/Linux:
        ```bash
        python3 -m venv venv
        source venv/bin/activate
        ```
    *   On Windows:
        ```bash
        python -m venv venv
        .\venv\Scripts\activate
        ```

3.  **Install Dependencies**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the Flask Development Server**

    ```bash
    # Make sure your virtual environment is activated
    export FLASK_APP=app.py  # On Windows use `set FLASK_APP=app.py`
    export FLASK_ENV=development # Enables debug mode and auto-reloading
    flask run
    ```
    
    Alternatively, you can run the `app.py` script directly (mainly for quick testing, `flask run` is preferred for development):
    ```bash
    python app.py 
    ```

5.  **Access the Application**

    Open your web browser and navigate to:
    [http://127.0.0.1:5000](http://127.0.0.1:5000) (or the URL provided by Flask in the terminal).

## Usage

1.  Enter a Cookiecutter template source in the input field. This can be:
    *   A Git repository URL (e.g., `https://github.com/cookiecutter/cookiecutter-pypackage.git`)
    *   An absolute path to a template directory on the server where the app is running (e.g., `/Users/youruser/templates/my-template`).
2.  Click "Load Template".
3.  If the template is loaded successfully, a form will appear with fields defined in the template's `cookiecutter.json`.
4.  Fill out the form with your desired project details.
5.  Click "Generate Project".
6.  If successful, your browser will download a ZIP file containing the generated project.

## Directory Structure

```
cookiecutter-webapp/
├── app.py                    # Flask application entrypoint
├── requirements.txt          # Dependencies
├── templates/                # Jinja2 HTML templates
│   ├── index.html
│   └── error.html
├── static/
│   └── js/
│       └── main.js           # Frontend JavaScript
├── tmp/                      # Auto-created for cloned/copied templates (cleaned periodically)
├── output/                   # Auto-created for generated projects & zips (cleaned after download)
└── README.md                 # This file
```

## Notes

- The in-memory storage for template sessions is basic and will not work correctly with multiple server workers (e.g., when deployed with Gunicorn using >1 worker).
- File path access is basic; ensure the server process has permissions for the specified paths and consider security implications.
- Temporary files (`tmp/`, `output/`) are cleaned up, but ensure the cleanup mechanism is robust for your deployment environment. 