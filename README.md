# Bring Loader

A simple shopping list generator for recurring purchases.

Create reusable groups—such as meals, bathroom supplies or cleaning products—select how many times to include each group, then send the combined shopping list to Bring!.

## Features

- Mobile-friendly interface with +/− quantity controls.
- Reusable shopping groups and a shared item catalogue.
- One standard unit per item, so quantities combine consistently.
- Preview the combined list before sending.
- Bring! account and destination list configured through the app.
- SQLite storage with persistent Docker data.
- One shared app login per installation.

Bring Loader uses the community `bring-api` package and is not affiliated with Bring!.

## Install with Docker Compose

Requires Docker with Docker Compose.

Clone the repository and create your configuration:

```bash
git clone https://github.com/aoconnor-irl/bring_loader.git
cd bring_loader
cp .env.example .env
```

Generate the two configuration keys:

```bash
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose build
docker compose run --rm --no-deps bring-loader python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the first output in `.env` as `APP_SECRET_KEY` and the second as `ENCRYPTION_KEY`.

Copy each value exactly, without quotes. Preserve the trailing `=` on the encryption key. Keep both keys unchanged after setup.

For access from other devices on your network, set `HOST_BIND` to the Docker host's LAN IP. The default, `127.0.0.1`, allows access only from the host itself.

On Linux, prepare the persistent data directory:

```bash
mkdir -p data
sudo chown 10001:10001 data
chmod 600 .env
```

Start the application and set an app password:

```bash
docker compose up -d
docker compose exec -it bring-loader flask --app bring_loader.app:create_app set-password
```

Use a password of at least **8 characters**.

Open `http://<host-address>:8723` and sign in. The container restarts automatically with Docker unless it has been deliberately stopped.

## Using the app

1. Open **Settings**, save your Bring! account details, then connect and select a list.
2. Create items in the **Item catalogue**, choosing their usual units. A blank unit means a simple count.
3. Create **Groups** and add items with quantities.
4. On **Shop**, use +/− to select groups and counts.
5. Preview the combined quantities and send them to Bring!.

The app sends all selected items. Make any shopping-run adjustments in Bring! afterwards.

Sending assumes the destination list is empty. It does not clear the list or inspect existing items. If sending fails partway through, check Bring! before retrying because some items may already have been added.

## Local development on Windows

Requires Python 3.12 or later. Run these commands in PowerShell from the project directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set `APP_SECRET_KEY` and `ENCRYPTION_KEY` in `.env` using the generated values.

Load the configuration and set your app password:

```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') } }
.\.venv\Scripts\flask.exe --app bring_loader.app:create_app set-password
```

Start the application:

```powershell
.\.venv\Scripts\python.exe run.py
```

Open http://127.0.0.1:8723.

Reload `.env` whenever you open a new PowerShell session. Stop the app with **Ctrl+C** before restarting it.

To test from another device on the same network, set `APP_BIND` to your PC's LAN IP before starting and allow the application port through Windows Firewall on the private network.

## Optional CSV import

The importer accepts two CSV files:

| File | Required columns |
|---|---|
| Groups | `Meal` |
| Group items | `Meal`, `Ingredient`, `Quantity`, `Measurement` |

Example files are included in `sample_data/`. The column name `Meal` can represent any shopping group.

Import before starting the app or setting its password. The importer requires a new database path and refuses to overwrite an existing database.

```powershell
.\.venv\Scripts\python.exe -m bring_loader.import_csv "Meals.csv" "Ingredients.csv" "data\bring_loader.sqlite3"
```

The importer validates names, quantities and group references. Review `UNIT_RESOLUTIONS` in `bring_loader/import_csv.py` before importing: it currently contains legacy resolutions for Onion, Lettuce and Rice. Clear or adapt those mappings for your data.

Keep personal exports in `private_data/`, which is excluded from Git.

## Updates

Back up your database and configuration before updating.

```bash
git pull
docker compose up -d --build
docker compose logs --tail=100 bring-loader
```

Check release instructions for any database changes. Automatic schema migrations are not currently implemented.

## Backup and restore

Back up both:

- `data/bring_loader.sqlite3`
- `.env`

The database contains your groups, items, app password hash and encrypted Bring! password. The encryption key in `.env` is required to recover the saved Bring! credentials.

For a consistent file backup, stop the application before copying these files, then start it again:

```bash
docker compose stop bring-loader
# Copy the database and .env to your protected backup location.
docker compose start bring-loader
```

To restore, stop the application, restore both files, ensure the data directory and database are writable by container UID `10001` on Linux, then start it again.

## Configuration and privacy

Do not commit `.env`, databases, personal exports or credentials. These paths are excluded by `.gitignore`.

Bring! passwords are encrypted before storage. Keep backups containing the database and encryption key protected.

For access over the Internet, configure HTTPS through a reverse proxy and set `COOKIE_SECURE=1`.

## Tests

```powershell
py -3 -m unittest discover -s tests
```

Automated tests do not send anything to Bring!.