### Zero Touch

Zero-touch document processing for Frappe and ERPNext: turns unstructured business documents into validated, draft ERPNext transactions.

### Installation

See the complete [installation and upgrade guide](docs/INSTALL.md) before installing. It covers the CPU PyTorch constraint, Tesseract OCR packages, local translation and transcription models, HTTPS microphone access, site migration, and verification.

Basic installation on a bench that already has Frappe and ERPNext:

```bash
cd $PATH_TO_YOUR_BENCH
PIP_CONSTRAINT=apps/zero_touch/constraints-translation.txt \
PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
  bench get-app zero_touch $URL_OF_THIS_REPO --branch main
bench --site your-site.example install-app zero_touch
bench --site your-site.example migrate
bench build --app zero_touch
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/zero_touch
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
# Zero-Touch
