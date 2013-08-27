"""Site-specific settings

This is the file that you should edit to customize the setting of your
PTS installation. By default it imports settings from the ``selected.py``
file which is a symlink to the type of installation to you have
(typically, ``production.py`` or ``development.py``) and lets you add
overrides on top of those type-of-installation-specific settings.
"""
# Load the selected configuration (selected.py is a symlink to preferred config)
from .selected import *

## Add your custom settings here

# ADMINS = (
#     ('Your Name', 'your_email@example.com'),
# )
# MANAGERS = ADMINS

# PTS_VENDOR_NAME = "Debian"
# PTS_VENDOR_URL = "http://www.debian.org"
# PTS_FQDN = "packages.qa.debian.org"

# If you don't use the packaged version of the PTS, put a random secret
# key here. DO NOT USE THE EXAMPLE KEY GIVEN BELOW.
# SECRET_KEY = 'etu2#5lv=!0(g9l31mw=cpwhioy!egg60lb5o3_67d83#(wu-u'
