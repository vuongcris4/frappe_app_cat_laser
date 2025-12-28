### Cat Laser

cat

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app [$URL_OF_THIS_REPO](https://github.com/vuongcris4/frappe_app_cat_laser) --branch develop
bench install-app cat_laser
```

## Dependencies

Before installing this app, install required Python packages:

```bash
bench pip install --system -r apps/cat_laser/cat_laser/requirements.txt


### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/cat_laser
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
