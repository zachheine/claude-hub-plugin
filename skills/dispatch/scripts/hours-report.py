#!/usr/bin/env python3
"""Moved in plugin 4.0 to skills/books/scripts/hours-report.py. This shim runs it, so
scheduled tasks and notes that still name the old path keep working. Point them at the
new path; the shim will be removed in a later major version."""
import os, runpy, sys
target = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'books', 'scripts', 'hours-report.py')
sys.argv[0] = os.path.normpath(target)
runpy.run_path(sys.argv[0], run_name='__main__')
