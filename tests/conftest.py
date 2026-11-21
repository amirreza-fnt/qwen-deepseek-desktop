import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
# The original test-suite asserts the Persian UI; English is covered by test_i18n.py.
from app import i18n
i18n.set_language('fa')
