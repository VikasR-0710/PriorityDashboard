import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DelineaSlackContractTests(unittest.TestCase):
    def test_slack_uses_xactly_support_secret_15978(self):
        loader = (ROOT / "config" / "delinea_loader.py").read_text()
        self.assertIn("_SLACK_SECRET_ID = 15978", loader)
        self.assertIn("secret = _get_secret(_SLACK_SECRET_ID)", loader)
        self.assertIn('_field(secret, "API Key")', loader)


if __name__ == "__main__":
    unittest.main()
