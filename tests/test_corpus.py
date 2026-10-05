from onlabel.data.corpus import label_name


def test_a_label_is_named_by_its_own_brand_first_and_keeps_shared_brands():
    # Rybelsus's label also covers Ozempic tablets; it must not read as the Ozempic injection label.
    assert label_name(["OZEMPIC", "RYBELSUS"], "rybelsus") == "RYBELSUS and OZEMPIC"
    assert label_name(["OZEMPIC"], "ozempic") == "OZEMPIC"


def test_device_presentations_are_not_extra_brands():
    assert label_name(["MOUNJARO", "MOUNJARO KWIKPEN"], "mounjaro") == "MOUNJARO"
    assert label_name([], "lantus") == "LANTUS"
