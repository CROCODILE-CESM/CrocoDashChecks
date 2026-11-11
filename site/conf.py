"""Sphinx settings for the CrocoDashChecks site.

The pages are Markdown (.md) and Jupyter notebooks (.ipynb). Every build runs
the notebooks, which read the results JSON, so the site always shows the
latest results. Build it with:

    pip install -r site/requirements.txt
    sphinx-build site site/_build/html
    python site/write_badges.py
"""

project = "CrocoDashChecks"
author = "CROCODILE"
html_title = "CrocoDashChecks"

extensions = ["myst_nb"]  # Markdown and notebooks as pages
exclude_patterns = ["_build", "**.ipynb_checkpoints", "requirements.txt"]

# The same theme as CrocoDash's documentation.
html_theme = "sphinx_book_theme"
html_theme_options = {
    "repository_url": "https://github.com/CROCODILE-CESM/CrocoDashChecks",
    "use_repository_button": True,
}

# Notebooks
nb_execution_mode = "force"  # run every notebook on every build
nb_execution_raise_on_error = True  # a notebook that errors fails the build
nb_execution_timeout = 300  # seconds per cell
nb_remove_code_source = True  # show each cell's output, not its code
nb_output_stderr = "remove"  # leave warnings out of the pages
nb_render_markdown_format = "myst"  # Markdown a cell prints can hold tables and links
nb_code_prompt_show = "Show the numbers"  # the toggle on folded tables
nb_code_prompt_hide = "Hide the numbers"

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3
