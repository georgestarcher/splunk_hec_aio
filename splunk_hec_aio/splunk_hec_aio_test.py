""" Import Modules """
import unittest

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio

class TestSplunkHEC(unittest.TestCase):
    """ Splunk HTTP Event Collector Class Tests """

    testHEC = SplunkHecAio("test.local","testToken")
    trustHEC1 = SplunkHecAio("http-inputs-splunktrust.splunkcloud.com","testToken")
 
    def test_defaults(self):
        """ Check HEC Sender Default Values """
        self.assertTrue(self.testHEC.get_pop_empty_fields())
        self.assertTrue(self.testHEC.get_payload_json_format())
        self.assertEqual(self.testHEC.get_concurrent_post_limit(), 10)
        self.assertEqual(self.testHEC.get_port(), 8088)
        self.assertEqual(self.testHEC.get_post_max_byte_size(), 512000)
        self.assertTrue(self.testHEC.get_verify_tls())
        self.assertTrue(self.testHEC.get_https())

    def test_set_pop_fields_type(self):
        """ Check set pop fields for non bool types """
        self.testHEC.set_pop_empty_fields("True")
        self.assertEqual(self.testHEC.get_pop_empty_fields(),True)

    def test_set_json_format_type(self):
        """ Check set json payload format for non bool types """
        self.testHEC.set_payload_json_format("True")
        self.assertEqual(self.testHEC.get_payload_json_format(),True)

    def test_set_https_type(self):
        """ Check set http url header for non bool types """
        self.testHEC.set_https("True")
        self.assertEqual(self.testHEC.get_https(),True)

    def test_set_tls_verify_type(self):
        """ Check set tls verification for non bool types """
        self.testHEC.set_verify_tls("True")
        self.assertEqual(self.testHEC.get_verify_tls(),True)

    def test_max_concurrent_post_type(self):
        """ Check set max currrent posts for non int types """
        self.testHEC.set_concurrent_post_limit("True")
        self.assertEqual(self.testHEC.get_concurrent_post_limit(), 10)

    def test_max_byte_size_values(self):
        """ Check max post bytes values for valid handling """
        self.testHEC.set_post_max_byte_size(1000000)
        self.assertEqual(self.testHEC.get_post_max_byte_size(), 800000)
        self.testHEC.set_post_max_byte_size(-1000000)
        self.assertEqual(self.testHEC.get_post_max_byte_size(), 800000)
        self.testHEC.set_post_max_byte_size(1000)
        self.assertEqual(self.testHEC.get_post_max_byte_size(), 4000)

    def test_max_byte_type(self):
        """ Check set max post bytes for valid int """
        # reset to default before test
        self.testHEC.set_post_max_byte_size()
        self.testHEC.set_post_max_byte_size("4000")
        self.assertEqual(self.testHEC.get_post_max_byte_size(), 512000)

    def test_connectivity_fake(self):
        """ Test result of invalid Splunk HEC Server """
        self.assertFalse(self.testHEC.check_connectivity())

    def test_connectivity_real_bad_token(self):
        """ Test result of invalid Splunk HEC Server token"""
        self.trustHEC1.set_port(443)
        self.assertFalse(self.trustHEC1.check_connectivity())

if __name__ == '__main__':
    unittest.main()
