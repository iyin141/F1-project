import os
import sys

os.environ['DJANGO_SETTINGS_MODULE'] = 'f1_project.settings_test'

if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main(sys.argv[1:]))
