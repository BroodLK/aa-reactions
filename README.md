![license](https://img.shields.io/badge/license-GPLv3-green?style=for-the-badge)
![python versions](https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge)
![django versions](https://img.shields.io/badge/django-4.2%2B-blue?style=for-the-badge)

# AA Reactions

AA Reactions is a plugin for Alliance Auth that provides tools for planning and calculating EVE Online reactions. It helps industrialist pilots optimize their production chains by calculating requirements, profits, and logistics based on their available materials.

## Index

- [AA Reactions](#aa-reactions)
  - [Core Requirements](#core-requirements)
  - [Install Instructions](#install-instructions)
- [Features](#features)
  - [Reaction Planner](#reaction-planner)
  - [Refining & Reprocessing](#refining--reprocessing)
  - [Economic Analysis](#economic-analysis)
- [Permissions](#permissions)

## Core Requirements
### The following AllianceAuth plugins are **_required_**:

```md
allianceauth >= 4.3.1
django-eveonline-sde
django-esi
```

## Install Instructions
After making sure to add the above prerequisite applications.
```bash
source /home/allianceserver/venv/auth/bin/activate && cd /home/allianceserver/myauth/
```
```bash
pip install git+https://github.com/BroodLK/aa-reactions.git#egg=aa-reactions
```
```bash
vi myauth/settings/local.py
```
Add `eve_sde` and `aareactions` to your `INSTALLED_APPS`.
```bash
python manage.py migrate && python manage.py collectstatic --noinput
```
### Initial Data Import
You **MUST** import the reaction definitions for the plugin to function:
```bash
python manage.py import_reactions
```
restart the things
exit your venv
```bash
sudo supervisorctl restart myauth:
```

## Features

### Reaction Planner
The core of the application is a powerful reaction planner that allows you to:
- **Input Parsing**: Paste items directly from your EVE inventory, assets, or cargo holds.
- **Chain Calculation**: Automatically determine the full multi-step reaction chain required to produce your desired end products.
- **Missing Materials**: Identifies exactly what materials you are missing and calculates the cost to acquire them.
- **Time Estimates**: Provides a total time required for the entire production chain.

### Refining & Reprocessing
- **Automatic Refinement**: Automatically calculates refined outputs from unrefined materials (like Moon Ores) based on your configured refine rates.
- **Skill Integration**: Supports character-specific skill levels for scrap metal processing and reprocessing to provide accurate output estimates.

### Economic Analysis
- **Profit & Loss**: Detailed breakdown of profit and loss for each reaction step and the final product.
- **Cost Index Integration**: Dynamic fetching of system-specific industry (Reactions) cost indices from ESI.
- **Configurable Fees**: Support for broker fees, sales taxes, SCC taxes, and facility taxes.
- **Price Basis**: Choose between Buy or Sell price basis for both inputs and outputs.

## Permissions

| Permission | Description |
|---|---|
| **basic_access** | Can access the Reactions tool and perform calculations. |
| **reactions_admin** | Can manage app-wide default reaction settings. |
