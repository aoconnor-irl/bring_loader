import tempfile
import unittest
from pathlib import Path
from bring_loader.core import aggregate, connect
from bring_loader.import_csv import import_files, prepare


class ImportTest(unittest.TestCase):
    def test_sample_import_and_aggregation(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "app.db"
            result = import_files(db, root / "sample_data/meals.csv", root / "sample_data/ingredients.csv")
            self.assertEqual(result[:3], (3, 6, 7))
            conn = connect(db)
            selected = {r["id"]: 2 if r["name"] == "Pasta Night" else 1
                        for r in conn.execute("SELECT id,name FROM groups") if r["name"] != "Bathroom Restock"}
            self.assertIn(("Onion", "3", ""), aggregate(conn, selected))
            self.assertIn(("Pasta", "1000", "g"), aggregate(conn, selected))
            conn.close()

    def test_unknown_unit_conflict_fails_without_creating_database(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder)/"meals.csv", Path(folder)/"ingredients.csv"
            a.write_text("Meal\nDinner\n", encoding="utf-8")
            b.write_text("Meal,Ingredient,Quantity,Measurement\nDinner,Onion,1,bag\nDinner,Onion,2,kg\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                prepare(a, b, resolutions={})


if __name__ == "__main__":
    unittest.main()
