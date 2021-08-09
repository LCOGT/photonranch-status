
from helpers import _empty_strings_to_dash


def test_empty_strings_to_dash():
    test_object = {
        "emptystring": "",
        "nonemptystring": "not empty"
    }
    processed = _empty_strings_to_dash(test_object)
    assert processed['emptystring'] == '-'
    assert processed['nonemptystring'] == 'not empty'
