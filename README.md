### CGM Worldwide Shipping

ERPNext shipment clearance for CGM Worldwide Shipping — air, sea, road, and export operations.

**Module:** `CGM Worldwide Shipping` — CRM pre-shipment, Project sea-import workflow, and guide-aligned doctypes (`Shipment Dossier`, `Container Tracker`, etc.). See [RESTRUCTURE.md](RESTRUCTURE.md) and [TEST_E2E.md](TEST_E2E.md).

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app cgm_shipping
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/cgm_shipping
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
