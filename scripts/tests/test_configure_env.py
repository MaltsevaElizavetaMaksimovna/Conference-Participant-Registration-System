import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "configure_env.py"


class ConfigureEnvTests(unittest.TestCase):
    def load_module(self):
        self.assertTrue(SCRIPT.is_file(), "Нужен генератор локального .env")
        spec = importlib.util.spec_from_file_location("configure_env", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_creates_distinct_credentials_and_private_file(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".env"
            module.create_env(path)
            values = dict(
                line.split("=", 1)
                for line in path.read_text("utf-8").splitlines()
                if line and not line.startswith("#")
            )
            self.assertGreaterEqual(len(values["POSTGRES_PASSWORD"]), 32)
            self.assertGreaterEqual(len(values["RS_SECRET_KEY"]), 32)
            self.assertNotEqual(values["POSTGRES_PASSWORD"], values["RS_SECRET_KEY"])
            self.assertEqual(values["HTTP_BIND"], "127.0.0.1")

    def test_existing_env_is_never_overwritten(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".env"
            path.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                module.create_env(path)
            self.assertEqual(path.read_text("utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
