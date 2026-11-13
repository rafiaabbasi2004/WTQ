"""Unit tests for the deterministic parts of the pipeline (no API key or network needed).

Run from the source/ folder:  python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bill_decoder.extract import _vote, check_consistency, normalise  # noqa: E402
from bill_decoder.qa import Extras, PaymentRecord, UsageMonth, compute_metrics  # noqa: E402
from bill_decoder.schema import Bill, Charge, Tax  # noqa: E402


class NormaliseTests(unittest.TestCase):
    def test_label_overrides_type_within_section(self):
        b = Bill(charges=[Charge(type="fpa", amount=52.91, label="Uniform Quarterly Adjustment"),
                          Charge(type="other", amount=64.93, label="Additional Surcharge (PHL)"),
                          Charge(type="other", amount=125.27, label="FCA :Apr-26")])
        types = [c.type for c in normalise(b).charges]
        self.assertEqual(types, ["quarterly_adjustment", "surcharge", "fpa"])

    def test_lone_generic_tax_line_becomes_total_taxes(self):
        b = Bill(taxes=[Tax(type="gst", amount=3358.23, label="Taxes")])
        b = normalise(b)
        self.assertEqual(b.taxes, [])
        self.assertEqual(b.total_taxes, 3358.23)

    def test_named_tax_lines_are_kept(self):
        b = Bill(taxes=[Tax(type="other_tax", amount=520.21, label="Sales Tax u/s 3(1)"),
                        Tax(type="other_tax", amount=29.41, label="Electricity Duty")])
        self.assertEqual([t.type for t in normalise(b).taxes], ["gst", "electricity_duty"])

    def test_zero_lines_dropped_and_subsidy_negative(self):
        b = Bill(charges=[Charge(type="energy", amount=100), Charge(type="fixed", amount=0),
                          Charge(type="subsidy", amount=3332, label="Subsidies")])
        out = normalise(b).charges
        self.assertEqual([(c.type, c.amount) for c in out], [("energy", 100), ("subsidy", -3332)])

    def test_tax_subtotal_equal_to_whole_bill_is_nulled(self):
        b = Bill(total_charges=29807, total_taxes=38323, current_bill=38323)
        self.assertIsNone(normalise(b).total_taxes)

    def test_grand_total_row_shift_is_repaired(self):
        b = Bill(total_charges=29807, total_taxes=38323, current_bill=69897, arrears=31203,
                 payable_within_due_date=69897)
        b = normalise(b)
        self.assertEqual((b.current_bill, b.total_taxes), (38323, None))


class ConsistencyTests(unittest.TestCase):
    def test_clean_bill_has_no_issues(self):
        b = Bill(previous_reading=8819, current_reading=8970, units_consumed=151,
                 charges=[Charge(type="energy", amount=2860.62)], total_charges=2860.62,
                 taxes=[Tax(type="gst", amount=569.62)], total_taxes=569.62, current_bill=3430.24,
                 payable_within_due_date=3430, payable_after_due_date=3716)
        self.assertEqual(check_consistency(b), [])

    def test_empty_charges_with_total_is_flagged(self):
        self.assertTrue(check_consistency(Bill(total_charges=1000)))

    def test_fpa_printed_outside_subtotal_is_not_flagged(self):
        b = Bill(charges=[Charge(type="energy", amount=6102), Charge(type="subsidy", amount=-3332),
                          Charge(type="fpa", amount=267)], total_charges=2770)
        self.assertEqual(check_consistency(b), [])


class VoteTests(unittest.TestCase):
    def test_majority_wins_and_ties_keep_first(self):
        a, b = Bill(tariff="A-1A(01)", current_bill=100), Bill(tariff="A-1a(01)", current_bill=100)
        self.assertEqual(_vote([a, a, b]).tariff, "A-1A(01)")
        self.assertEqual(_vote([a, b]).tariff, "A-1A(01)")


class MetricsTests(unittest.TestCase):
    def setUp(self):
        months = [("2025-04", 141), ("2025-06", 197), ("2025-07", 239), ("2025-12", 124), ("2026-01", 96),
                  ("2026-02", 88), ("2026-03", 115), ("2026-04", 151)]
        self.extras = Extras(usage_history=[UsageMonth(month=m, units=u) for m, u in months],
                             payment_history=[PaymentRecord(month="2026-03", billed=100, paid=0)])
        self.bill = {"bill_month": "2026-04", "units_consumed": 151, "current_bill": 3430.24, "total_taxes": 569.62,
                     "total_charges": 2860.62, "payable_within_due_date": 3430, "payable_after_due_date": 3716,
                     "charges": [], "taxes": []}

    def test_tax_share_and_late_payment(self):
        m = compute_metrics(self.bill, self.extras)
        self.assertAlmostEqual(m["taxes_percent_of_current_bill"], 16.61, places=2)
        self.assertEqual(m["late_payment_extra_amount"], 286.0)

    def test_history_facts(self):
        m = compute_metrics(self.bill, self.extras)
        self.assertEqual(m["same_month_last_year_units"], 141)
        self.assertEqual(m["highest_month_in_previous_12"], {"month": "2025-07", "units": 239})
        self.assertEqual(m["months_with_no_payment_recorded"], ["2026-03"])
        self.assertEqual(m["previous_month_units"], 115)
        self.assertEqual(m["last_3_months_units"], {"2026-02": 88, "2026-03": 115, "2026-04": 151})


if __name__ == "__main__":
    unittest.main()
