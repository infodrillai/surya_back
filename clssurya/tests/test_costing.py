import unittest

from clssurya.utils.costing import allocate_extra, split_gst, stage1_wastage, stage_totals


class TestCosting(unittest.TestCase):
    def test_stage1_example(self):
        t = stage_totals(0, 10 * 250, 5, 99)
        self.assertAlmostEqual(t["rejection_amount"], 125)
        self.assertAlmostEqual(t["batch_total"], 2625)
        # Unit cost spread over accepted output: 2625 / (99 * 0.95) = 27.91068...
        self.assertAlmostEqual(t["unit_cost"], 27.9107, places=4)
        self.assertAlmostEqual(stage1_wastage(10, 99, 0.1), 0.1, places=9)

    def test_stage2_example(self):
        carried = 100 * 26.5152
        self.assertAlmostEqual(carried, 2651.52, places=2)
        t = stage_totals(carried, 400, 5, 100)
        self.assertAlmostEqual(t["base"], 3051.52, places=2)
        self.assertAlmostEqual(t["rejection_amount"], 152.576, places=3)
        self.assertAlmostEqual(t["batch_total"], 3204.096, places=3)
        # Unit cost spread over accepted output: 3204.096 / (100 * 0.95) = 33.7273...
        self.assertAlmostEqual(t["unit_cost"], 33.7273, places=4)

    def test_gst_split(self):
        self.assertEqual(split_gst(1000, 18, "Gujarat", "gujarat"), {"cgst": 90, "sgst": 90, "igst": 0})
        self.assertEqual(split_gst(1000, 18, "Kerala", "Gujarat"), {"cgst": 0, "sgst": 0, "igst": 180})

    def test_landed_allocation(self):
        self.assertEqual(allocate_extra([100, 300], 40), [10, 30])


if __name__ == "__main__":
    unittest.main()
