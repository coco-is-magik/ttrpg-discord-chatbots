from ttrpg_chatbots.cli import greet, main


def test_greet_defaults_to_world() -> None:
    assert greet() == "Hello, world!"


def test_greet_uses_given_name() -> None:
    assert greet("Tav") == "Hello, Tav!"


def test_main_prints_greeting(capsys) -> None:
    main()
    assert capsys.readouterr().out == "Hello, world!\n"
