from store.keys import mk_k, mk_k_prefix
from store.reader import Reader
from store.writer import Writer


def test_a_key_is_kind_and_identifier():
    assert mk_k("user", "7") == "user:7"


def test_a_prefix_covers_one_kind():
    assert mk_k_prefix("user") == "user:"


def test_what_is_written_can_be_read():
    backing = {}
    Writer(backing).save("user", "7", "Ada")
    assert Reader(backing).load("user", "7") == "Ada"


def test_everything_of_one_kind_comes_back():
    backing = {}
    writer = Writer(backing)
    writer.save_many("user", {"1": "Ada", "2": "Grace"})
    writer.save("post", "9", "hello")
    assert Reader(backing).all_of("user") == ["Ada", "Grace"]
