// static/js/main.js

document.addEventListener('DOMContentLoaded', () => {
    const sourceForm = document.getElementById('source-form');
    const contextForm = document.getElementById('context-form');
    const sourceInput = document.getElementById('source');
    const cookiecutterFormContainer = document.getElementById('cookiecutter-form-container');
    const templateIdInput = document.getElementById('template_id');
    const errorMessageDiv = document.getElementById('error-message');
    const loadingSpinner = document.getElementById('loading-spinner');

    // --- Helper Functions ---
    function displayError(message) {
        errorMessageDiv.textContent = message;
        errorMessageDiv.style.display = 'block';
        loadingSpinner.style.display = 'none'; // Hide spinner on error
        console.error(message);
    }

    function clearError() {
        errorMessageDiv.textContent = '';
        errorMessageDiv.style.display = 'none';
    }

    function setLoading(isLoading) {
        loadingSpinner.style.display = isLoading ? 'inline-block' : 'none';
        // Optionally disable buttons during loading
        sourceForm.querySelector('button[type="submit"]').disabled = isLoading;
        if (contextForm.style.display !== 'none') {
           contextForm.querySelector('button[type="submit"]').disabled = isLoading;
        }
    }

    function renderCookiecutterForm(fields, templateId) {
        const formContent = contextForm.querySelector('#context-form-fields') || document.createElement('div');
        formContent.id = 'context-form-fields';
        formContent.innerHTML = ''; // Clear previous fields

        fields.forEach(field => {
            // Basic input type mapping (can be extended)
            let inputType = "text";
            if (field.type === "integer") {
                inputType = "number";
            } else if (field.type === "boolean") {
                inputType = "checkbox"; // Consider how to represent booleans
            } else if (field.type === "select") {
                 inputType = "select"; // Requires options
            }

            const formGroup = document.createElement('div');
            formGroup.className = 'mb-3';

            const label = document.createElement('label');
            label.htmlFor = field.name;
            label.className = 'form-label';
            // Attempt to make label more readable (e.g., project_name -> Project Name)
            label.textContent = field.name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

            let inputElement;
            if (inputType === 'select') {
                inputElement = document.createElement('select');
                inputElement.className = 'form-select';
                (field.options || []).forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt;
                    option.text = opt;
                    if (opt === field.default) {
                        option.selected = true;
                    }
                    inputElement.appendChild(option);
                });
            } else if (inputType === 'checkbox') {
                 formGroup.className = 'mb-3 form-check';
                 inputElement = document.createElement('input');
                 inputElement.type = 'checkbox';
                 inputElement.className = 'form-check-input';
                 if (String(field.default).toLowerCase() === 'true' || String(field.default) === 'y' || String(field.default) === 'yes') {
                    inputElement.checked = true;
                 }
                 label.className = 'form-check-label'; // Adjust label class for checkbox
            } else {
                inputElement = document.createElement('input');
                inputElement.type = inputType;
                inputElement.className = 'form-control';
                inputElement.value = field.default || '';
            }

            inputElement.id = field.name;
            inputElement.name = field.name;

            formGroup.appendChild(label);
             if(inputType !== 'checkbox') {
                formGroup.appendChild(inputElement);
            } else {
                // Checkbox input should come before the label visually in Bootstrap 5
                 formGroup.insertBefore(inputElement, label);
            }

            if (field.help_text) {
                const helpText = document.createElement('div');
                helpText.className = 'form-text';
                helpText.textContent = field.help_text;
                formGroup.appendChild(helpText);
            }

            formContent.appendChild(formGroup);
        });

        // Insert the fields before the hidden input and submit button
        contextForm.insertBefore(formContent, templateIdInput);

        templateIdInput.value = templateId;
        cookiecutterFormContainer.style.display = 'block';
        sourceForm.style.display = 'none'; // Hide the source input form
    }

    // --- Event Listeners ---

    // Handle Source Form Submission (/load)
    sourceForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        clearError();
        setLoading(true);

        const sourceValue = sourceInput.value.trim();
        if (!sourceValue) {
            displayError('Template source cannot be empty.');
            setLoading(false);
            return;
        }

        try {
            const response = await fetch('/load', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ source: sourceValue }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `Server responded with status ${response.status}`);
            }

            if (data.fields && data.template_id) {
                renderCookiecutterForm(data.fields, data.template_id);
            } else {
                throw new Error('Invalid response from server after loading template.');
            }

        } catch (error) {
            displayError(`Failed to load template: ${error.message}`);
        } finally {
            setLoading(false);
        }
    });

    // Handle Context Form Submission (/generate)
    contextForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        clearError();
        setLoading(true); // Consider a different loading indicator for generation?

        const formData = new FormData(contextForm);
        const context = {};
        const templateId = formData.get('template_id');

        // Convert FormData to a context object
        formData.forEach((value, key) => {
            if (key !== 'template_id') {
                // Handle checkbox values (might need adjustment based on cookiecutter expectation)
                const inputElement = contextForm.querySelector(`[name="${key}"]`);
                 if (inputElement && inputElement.type === 'checkbox') {
                     context[key] = inputElement.checked;
                 } else {
                    context[key] = value;
                 }
            }
        });

        if (!templateId) {
             displayError('Missing template ID. Please reload the template.');
             setLoading(false);
             return;
        }

        try {
            const response = await fetch('/generate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ template_id: templateId, context: context }),
            });

            if (!response.ok) {
                // Try to parse error JSON from server
                let errorMsg = `Server responded with status ${response.status}`;
                try {
                    const errorData = await response.json();
                    errorMsg = errorData.error || errorMsg;
                } catch (e) { /* Ignore if body is not JSON */ }
                throw new Error(errorMsg);
            }

            // Handle the file download
            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = downloadUrl;
            // Extract filename from Content-Disposition header, default to project.zip
            const disposition = response.headers.get('content-disposition');
            let filename = 'project.zip';
            if (disposition && disposition.indexOf('attachment') !== -1) {
                const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                const matches = filenameRegex.exec(disposition);
                if (matches != null && matches[1]) {
                    filename = matches[1].replace(/['"]/g, '');
                }
            }
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(downloadUrl);
            a.remove();

            // Optionally: Reset the form or redirect after successful download
            // location.reload(); // Simple reset
            alert('Project generated successfully and download started!');
             // Maybe reset to the initial state?
            // cookiecutterFormContainer.style.display = 'none';
            // sourceForm.style.display = 'block';

        } catch (error) {
            displayError(`Failed to generate project: ${error.message}`);
        } finally {
            setLoading(false);
        }
    });
}); 