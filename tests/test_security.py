# -*- coding: utf-8 -*-
"""Регрессионные проверки безопасности распаковки моделей перевода."""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config
import translator


class ModelArchiveSafetyTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="raspoz_security_")
        self.old_work = config.ARGOS_WORK_DIR
        config.ARGOS_WORK_DIR = os.path.join(self.root, "work")
        self.model = os.path.join(self.root, "model.argosmodel")

    def tearDown(self):
        config.ARGOS_WORK_DIR = self.old_work
        shutil.rmtree(self.root, ignore_errors=True)

    def test_valid_model_extracts_inside_work_dir(self):
        with zipfile.ZipFile(self.model, "w") as zf:
            zf.writestr("pkg/model/config.json", "{}")
            zf.writestr("pkg/sentencepiece.model", "model")
        result = translator._extract_model_dir(self.model)
        self.assertEqual(os.path.basename(result), "pkg")
        self.assertTrue(os.path.isfile(os.path.join(result, "sentencepiece.model")))
        self.assertTrue(os.path.isdir(os.path.join(result, "model")))

    def test_zip_slip_is_rejected(self):
        with zipfile.ZipFile(self.model, "w") as zf:
            zf.writestr("../escaped.txt", "must not be written")
            zf.writestr("pkg/model/config.json", "{}")
        with self.assertRaises(translator.TranslateError):
            translator._extract_model_dir(self.model)
        self.assertFalse(os.path.exists(os.path.join(self.root, "escaped.txt")))

    def test_absolute_member_is_rejected(self):
        with zipfile.ZipFile(self.model, "w") as zf:
            zf.writestr("/absolute.txt", "must not be written")
            zf.writestr("pkg/model/config.json", "{}")
        with self.assertRaises(translator.TranslateError):
            translator._extract_model_dir(self.model)


if __name__ == "__main__":
    unittest.main(verbosity=2)
