# Zero Touch: Installation Guide

This guide installs the `zero_touch` app on an existing Frappe v15 and ERPNext v15 bench, for a production server.

## 1. Requirements

| Item | Version | Notes |
|------|---------|-------|
| OS | Ubuntu 22.04 LTS (or Debian 12) | Same as the bench you already run |
| Frappe | v15 (tested: 15.121.1) | |
| ERPNext | v15 (tested: 15.87.2) | Required: Zero Touch creates ERPNext documents |
| Python | 3.10 to 3.12 | Frappe's virtualenv |
| MariaDB | 10.6 or later | |
| Redis | Installed by bench | |
| Tesseract OCR | 4.1 or later, with `eng` and `ara` language data | Reads scanned PDFs |
| Python package | `pdfplumber` 0.11 (MIT) | Installed automatically from `pyproject.toml` |
| Local translation | Argos Translate, CPU PyTorch, and language packs | Install the app with the translation constraint file below; Arabic↔English packs are downloaded separately |
| Audio transcription | faster-whisper | Uses the local CPU Whisper small model; the model downloads on first transcription |

The first audio transcription can take longer while the Whisper `small` model (about 460 MB) downloads. The selected audio language is passed to the model to improve recognition. Browser recording uses the user's microphone and requires microphone permission and HTTPS (or localhost). Run model warm-up commands as the same Linux user that runs the Frappe web and worker processes.

Licences of all dependencies are MIT, Apache-2.0, or BSD. Tesseract is Apache-2.0.

## 2. Install system packages (once per server)

Run as a user with sudo:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara
tesseract --version
tesseract --list-langs     # must list: ara, eng
```

If `ara` is missing, install the Arabic data package and check again. Zero Touch reads Arabic only when this language is present.

## 3. Get the app onto the server

Choose one method.

**A. From a Git repository (recommended)**

```bash
cd /home/frappe/frappe-bench          # your bench directory
PIP_CONSTRAINT=apps/zero_touch/constraints-translation.txt \
PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
  bench get-app zero_touch <git-url> --branch main
```

The constraint installs the CPU build of PyTorch used by Argos Translate. Set both variables for the `bench get-app` command so its editable install resolves dependencies with the CPU build from the start.

**B. From a copy of the folder**

Copy the `zero_touch` folder into `apps/`, then run:

```bash
cd /home/frappe/frappe-bench
PIP_CONSTRAINT=apps/zero_touch/constraints-translation.txt \
PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
  ./env/bin/pip install -e apps/zero_touch
echo "zero_touch" >> sites/apps.txt
```

Use the same bench user that owns the other apps.

If the app was already installed without those variables, resolve the app dependencies again with:

```bash
PIP_CONSTRAINT=apps/zero_touch/constraints-translation.txt \
PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
  ./env/bin/pip install -e apps/zero_touch
```

This installs the Python packages in `pyproject.toml`: `pdfplumber`, `argostranslate`, and `faster-whisper`, plus their Python dependencies. It does not install system OCR packages or model weights. Uploaded documents and text stay on this server during transcription and translation.

## 3.1 Download local models before first use (recommended)

Run as the bench service user from the bench root. The translation pair downloads are about 100 MB each on average. Other translation targets download their language pair the first time that target is selected.

```bash
./env/bin/python - <<'PY'
import argostranslate.package

packages = argostranslate.package.get_available_packages()
for source, target in (("ar", "en"), ("en", "ar")):
    package = next(p for p in packages if p.from_code == source and p.to_code == target)
    argostranslate.package.install_from_path(package.download())
PY

./env/bin/python -c 'from faster_whisper import WhisperModel; WhisperModel("small", device="cpu", compute_type="int8")'
```

Argos stores language packages under the service user's Argos data directory. Faster Whisper caches its model under that user's Hugging Face cache. Keep these directories writable and include them in server disk-space planning. If the service runs without internet access, download and warm the models before restricting outbound access.

## 4. Install on the site

Replace `your-site.example` with the production site name.

```bash
cd /home/frappe/frappe-bench
bench --site your-site.example install-app zero_touch
bench --site your-site.example migrate
bench build --app zero_touch
bench --site your-site.example clear-cache
```

`install-app` creates the DocTypes, the six Zero Touch roles, and the default Document Types (Sales Invoice, Supplier Invoice, Customer). `migrate` runs the setup patch again. It is safe to run more than once.

> `migrate` runs the pending patches for every app on the site. Check the list before running it on a live site, or take a backup first: `bench --site your-site.example backup --with-files`.

## 5. Start the background services

Zero Touch processes documents in the background, so both a worker and the scheduler must run.

```bash
bench setup supervisor       # if not already done
sudo supervisorctl reread && sudo supervisorctl update
```

Or with systemd or the Procfile, make sure these run:

- `bench worker` (or `bench worker --queue default`). It must run for every site that uses Zero Touch.
- `bench schedule`. It runs the 5-minute maintenance job that recovers stalled documents and retries failed ones.

Check that they are up:

```bash
ps -eo args | grep "[b]ench.*worker"
ps -eo args | grep "[b]ench.*schedule"
```

## 6. Configure the site

1. Log in as an administrator, open **Zero Touch → Zero Touch Settings**.
2. Check the defaults: maximum file size (20 MB), allowed file types, maximum automatic attempts (5).
3. Tick **Enable Zero Touch Processing**, then save.
4. Give users access:
   - **Zero Touch Uploader**: uploads documents. Sees only their own documents.
   - **Zero Touch Reviewer**: reviews and saves fields for the companies they can access.
   - **Zero Touch Manager**: configures mappings and reprocesses documents.
   - **Zero Touch Admin**: configures providers and settings. Cannot see financial content unless also a Reviewer or Manager.
5. Users see only the companies they have a **Company** User Permission for. Users with no company permission see nothing, by design.

## 7. Verify the installation

```bash
bench --site your-site.example execute frappe.get_installed_apps
bench --site your-site.example execute zero_touch.api.monitor.get_status_counts
```

Then in the browser:

1. **Zero Touch → Document Inbox → Upload Document**. Upload a text-based PDF, choose **Sales Invoice**.
2. The record should move from Queued to Processing to Pending Review within a minute.
3. Open **Review Center**. The page previews and the extracted fields should appear.
4. Open **Document Scanner**. Select **Image or PDF**, upload an image or PDF, and confirm the text appears beside its preview.
5. Select **Audio file or recording**, select the spoken language, then upload audio or record using the microphone. Confirm the transcript appears and can be edited.
6. Select a translation target and translate the edited text. Confirm the result appears below the source text.

Check the worker log for errors after the test: `tail -n 100 logs/worker.error.log`.

## 8. Mappings

**Zero Touch → Document Field Mapping** connects extracted fields to fields on the target document.

- Leave **Company** empty to use the mapping for all companies. Fill it in to override for one company.
- Only one enabled mapping can apply to a given document type and company.
- Transforms are a fixed list: `none`, `strip`, `upper`, `date_iso`, `money`, `digits_only`. They cannot be extended from the UI.

After saving the mapping, upload a document and open the **Review Center**. The mapping controls both what is read and the fields used when **Create** inserts the draft. Rows marked **ERPNext fills automatically** are left to ERPNext; required fields that neither the document nor ERPNext can fill produce a clear blocker.

## 9. Upgrade

```bash
cd /home/frappe/frappe-bench
cd apps/zero_touch
git pull --ff-only
cd ../..
PIP_CONSTRAINT=apps/zero_touch/constraints-translation.txt PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
  ./env/bin/pip install -e apps/zero_touch
bench --site your-site.example migrate
bench build --app zero_touch
bench --site your-site.example clear-cache
```

Restart the worker after any update, so it loads the new code:

```bash
sudo supervisorctl restart all    # or restart your worker service
```

## 10. Uninstall

```bash
bench --site your-site.example uninstall-app zero_touch --yes
```

Uninstalling does not delete stored original files. Remove them from **File** if they are no longer needed. Processing logs are kept for audit.

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Upload failed" | Processing disabled, or settings missing | Enable processing in Zero Touch Settings. Run `bench --site … migrate` |
| Document stays Queued | Worker not running | Start `bench worker` |
| Status Pending Review with "scanned document" | Tesseract missing or language data missing | Run section 2, then **Re-run Extraction** |
| Status Failed "PDF could not be read" | Encrypted or damaged PDF | Re-export the PDF, then upload again |
| Status Failed "OCR timed out" | Large scan on a slow server | Automatic retry runs later, or use **Retry** |
| Dropdown for Document Type is empty | Browser cached old script | Hard-refresh (Ctrl+Shift+R) |
| Arabic fields empty | Layout differs from the built-in labels | Send a sample to the developers; labels are configurable in a future release |
| "Documents are added by uploading a file" | Someone tried to create a record from the form | Use **Upload Document** instead |
| Audio language list stays empty | Audio-language endpoint errored or browser cached old assets | Check `logs/<site>.log`, rebuild assets, and hard-refresh the page |
| Microphone button is unavailable | Browser permission denied, no microphone, or site is not secure | Allow microphone access and use HTTPS or localhost |
| First audio transcription is slow or fails to download the model | Whisper model is not cached for the bench user | Run the model warm-up command in section 3.1 as the service user |
| Translation choices are missing | Translation package index is unreachable or asset cache is stale | Check server internet access and `logs/<site>.log`, then hard-refresh |
| CPU PyTorch resolver downloads CUDA dependencies | CPU constraint was not applied during app installation | Re-run the dependency installation in section 3 with both environment variables |

Logs:

- Web and application errors: `logs/<site>.log` and **Error Log** in the desk
- Worker: `logs/worker.log` and `logs/worker.error.log`
- Processing history for each document: **Review Center** → Processing History

## 12. Security checklist for production

- Use HTTPS only.
- Give Zero Touch Admin only to people who manage the system.
- Limit the upload size in both Zero Touch Settings and the web server (`client_max_body_size` in nginx).
- Keep **Keep Original Files** at 0 until a retention policy is agreed.
- Change any password that was shared in chat, plain text, or screenshots.
- Take a backup before the first migrate: `bench --site your-site.example backup --with-files`.
