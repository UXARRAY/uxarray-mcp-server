"""Remote execution on Globus Compute endpoints.

Function source is shipped to the worker (AllCodeStrategies), so submitter
and worker should run the same Python minor version; skew is reported by
the worker probe rather than refused here.
"""
