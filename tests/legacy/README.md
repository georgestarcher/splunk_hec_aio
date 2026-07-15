# Legacy tests

`splunk_hec_aio_test.py` is retained as historical test coverage, but it is not
part of the default deterministic suite. Two cases make network requests and
depend on external HEC behavior.

Do not run this module in pull-request CI. The protected **Live Splunk
integration** workflow is the maintained path for real HEC and search
verification.
