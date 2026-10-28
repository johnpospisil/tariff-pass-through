"""Tests for the HTSUS Chapter 99 list parsers (P08)."""

from tpt.build import hs_lists as hl


def test_table_hts8_reads_run_together_numbers_and_skips_ch98_99():
    text = "0101.90.300101.30.00\n9903.88.01 0102.29.40"
    assert hl.table_hts8(text) == ["01019030", "01013000", "01022940"]


def test_partial_items_include_hts8_and_exclude_10_digit_lines():
    text = (
        "are the following products of China:\n"
        "1. Machines ..., provided for in [subheading] 8517.62.00, except for such machines "
        "provided for in statistical reporting number 8517.62.0090;\n"
        "2. Seats ..., provided for in subheading 9401.71.00, except for such seats provided "
        "for in statistical reporting numbers 9401.71.0001, and 9401.71.00031.\n"
    )
    include, exclude = hl.partial_items(text)
    assert include == ["85176200", "94017100"]
    assert exclude == ["8517620090", "9401710001", "9401710031"]  # HTS typo 00031 -> 0031


def test_country_list_keeps_and_inside_names():
    text = (
        "the application of subheadings 9903.45.21 through 9903.45.25, the following developing "
        "countries that are members: Bosnia and Herzegovina, Saint Vincent and the Grenadines, "
        "Sao Tomé and Principe, Zambia and Zimbabwe. (c) next"
    )
    names = hl.country_list(text, "the application of subheadings 9903.45.21 through")
    assert names == ["Bosnia and Herzegovina", "Saint Vincent and the Grenadines",
                     "Sao Tomé and Principe", "Zambia", "Zimbabwe"]  # fmt: skip
