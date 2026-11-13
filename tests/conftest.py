import os
import tempfile

# every test run gets its own empty data folder, set before the app modules load
_tmp = tempfile.mkdtemp(prefix="jh-test-")
os.environ["EMPLOID_DATA"] = _tmp
