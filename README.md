# BlackDiamondHub

BlackDiamondHub is a Django-based web application designed to manage inventory, feedback, and sunpeaks webcams.

## Features

- Inventory management
- Feedback system
- Integration with Sunpeaks webcams
- User authentication and authorization

## Requirements

- Python 3.8+
- PostgreSQL
- Google Chrome and ChromeDriver
- libzbar0 (for barcode scanning)
- libpq-dev

## Installation

1. Clone the repository:

    ```sh
    git clone https://github.com/yourusername/BlackDiamondHub.git
    cd BlackDiamondHub
    ```

2. Create and activate a virtual environment:

    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. Install the required Python packages:

    ```sh
    pip install --upgrade pip
    pip install -r requirements.txt
    ```

4. Set up the environment variables. You can create a `.env` file in the root directory of the project with the following content:

    ```env
    DJANGO_SECRET_KEY=any-long-random-string
    DJANGO_DEBUG=true
    ALLOWED_HOSTS="List of hosts to allow to server this site"
    DB_HOST=your_db_host
    DB_NAME=your_db_name
    DB_USER=your_db_user
    DB_PASSWORD=your_db_password
    # Optional: table-owner login for the container's startup migrations.
    # When set, DB_USER only needs SELECT/INSERT/UPDATE/DELETE.
    DB_MIGRATE_USER=your_db_owner
    DB_MIGRATE_PASSWORD=your_db_owner_password
    SPOTIFY_CLIENT_ID=your_spotify_client_id
    SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
    ```

5. Apply the database migrations:

    ```sh
    python manage.py migrate
    ```

6. Create a superuser:

    ```sh
    python manage.py createsuperuser --username $ADMIN_USER --email admin@example.com
    ```

7. Run the development server:

    ```sh
    python manage.py runserver
    ```

8. Access the application at `http://127.0.0.1:8000/`.

## Sites

The same code runs at more than one house. Everything that differs lives in
`sites/<site>/`, and CI publishes one image per site:

| Site | Folder | Image tag |
|---|---|---|
| Sun Peaks (Black Diamond Lodge) | `sites/sunpeaks/` | `:latest` (also `:sunpeaks`, `:sha-<commit>`) |
| Mercer Island (Slivinski Hub) | `sites/mercerisland/` | `:mercerisland` (also `:sha-<commit>-mercerisland`) |

Each site folder has:

- `site.toml`: `[brand]` name, subtitle and monogram SVGs (the "BDH" monogram
  from `bdh-sdk` when none is given), `[location]` latitude, longitude and IANA
  time zone (screensaver season, night mode, sunrise/sunset), and `[features]`
  such as `mountain_weather`.
- `apps.txt`: the hashed app wheels baked into that site's image.

The image is built with `--build-arg HUB_SITE=<site>`, which also sets
`HUB_SITE` at runtime. On a server, pick the site's image with
`HUB_IMAGE_TAG=<tag>` in `.env` (unset is `:latest`, Sun Peaks).

To add a site: create `sites/<site>/site.toml` and `apps.txt`, then add it to
the matrices in `.github/workflows/docker-publish.yml` and `tests.yml`.

## Running Tests

To run the tests, use the following command:

```sh
python manage.py test -v 2