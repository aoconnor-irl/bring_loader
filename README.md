# Bring Loader

A small household shopping list generator. Define reusable groups of items (meals, bathroom supplies, etc.), select groups with counts, preview the combined quantities and send the result to one Bring! list. One app password and one Bring! account are shared by the household.

## Windows 11: first run

Install Python 3.12 or later and ensure `py` works in PowerShell. In the project directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put those two outputs in `.env` as `APP_SECRET_KEY` and `ENCRYPTION_KEY`. Keep the values stable: changing the encryption key makes saved Bring! credentials unreadable. Do not commit `.env` or your data directory. In PowerShell, load the settings for this terminal session:

```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') } }
.\.venv\Scripts\flask.exe --app bring_loader.app:create_app set-password
.\.venv\Scripts\python.exe run.py
```

Visit <http://127.0.0.1:8723>. Set a password of at least 12 characters. The password setup command can also change it later. `run.py` runs the same application code used by Docker, with a production WSGI server. For phone testing from the same Wi-Fi, set `APP_BIND` to your Windows PC LAN IP for that terminal session and allow that port through Windows Firewall on the private network. Do not expose the development PC to the Internet.

## Import your Google Sheets exports

Export **Meals** and **Ingredients** as CSV. Stop the app while doing the one-time import. It imports into a *new* database and refuses to overwrite an existing one:

```powershell
.\.venv\Scripts\python.exe -m bring_loader.import_csv "C:\path\Meals.csv" "C:\path\Ingredients.csv" "data\bring_loader.sqlite3"
```

Create the app password after importing, or run the import before the first app start. If the app already created `data\bring_loader.sqlite3`, back it up, delete the empty copy, import, then run `set-password` again. The importer rejects unexpected unit conflicts, duplicate group names, bad quantities, and unknown group references before creating a database. Adam's original export has explicit unit resolutions for Onion (blank/count), Lettuce (bag), and Rice (cup); inspect those defaults before applying the importer to other people's exports. For generic exports, adjust `UNIT_RESOLUTIONS` in `bring_loader/import_csv.py` or clear it to require explicit reconciliation.

## Bring! settings and sending

Sign in, open **Settings**, enter the Bring! email and password, choose **Connect and choose list**, then select the destination list. The password is encrypted using `ENCRYPTION_KEY` before it is stored in SQLite and is never displayed again. Select groups on **Shop**, preview, and send. Sending assumes the Bring! list starts empty and does not clear or inspect existing items. If a send fails partway through, check Bring! before retrying to avoid duplicates. Bring! integration uses the community `bring-api` package and may require updating if Bring! changes its service.

## Docker Compose (later, after local testing)

Copy the project to your Ubuntu host and create `.env` from `.env.example` with **persistent** keys. Set `HOST_BIND` to your server's LAN IP, or leave it on `127.0.0.1` behind a local reverse proxy. `data/` is bind-mounted to `/app/data`, so the database survives container recreation and reboots. On Linux, create and assign the data directory to container UID 10001 before starting:

```bash
mkdir -p data
sudo chown 10001:10001 data
docker compose up -d --build
docker compose exec -it bring-loader flask --app bring_loader.app:create_app set-password
```

For updates: back up `data/` and `.env`, pull the new source, run `docker compose up -d --build`, and check `docker compose logs --tail=100 bring-loader`. This project has no automatic schema migrations yet; future schema changes must include a documented migration before an update.

For a consistent backup, stop the container, copy `data/bring_loader.sqlite3` and the protected `.env` to a secure location, then restart:

```bash
docker compose stop bring-loader
cp data/bring_loader.sqlite3 /path/to/secure-backup/bring_loader.sqlite3
cp .env /path/to/secure-backup/bring_loader.env
docker compose start bring-loader
```

To restore, stop the container, restore both files together, check ownership (`10001:10001` for the database), then start it. The encryption key in the backed-up `.env` is required to read stored Bring! credentials. `docker compose down` does not remove the bind-mounted data directory; still keep backups.

The app login protects its pages, but a plain HTTP connection on the LAN does not encrypt traffic in transit. If you later open access beyond the LAN or tailnet, use HTTPS through a reverse proxy and set `COOKIE_SECURE=1`. Review access rules before exposing the service.

## Repository hygiene

Only the fictional CSVs in `sample_data/` are intended for a public repository. Original exports, SQLite databases, `.env`, tokens, credentials and server-specific configuration stay local. Before publishing, inspect `git status` and `git diff --cached --name-only` and check for secrets. The repository can be named `bring_loader`; the package and display name can be changed later.

Run the initial data-layer checks with `py -3 -m unittest discover -s tests`. Bring! live calls require your own credentials and are never made by automated checks.
