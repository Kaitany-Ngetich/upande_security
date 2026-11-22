"""Own analytics engine for cameras without built-in AI.

Runs on the site box, reads the cameras' streams locally, and emits the
same normalised events as camera-native analytics, so ERPNext treats both
the same way. Needs the optional extra:  pip install '.[engine]'
"""
