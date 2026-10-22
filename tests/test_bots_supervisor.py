"""The supervisor: who starts, who is dormant, and one failure does not sink the rest."""

from __future__ import annotations

import itertools

import asyncio
import logging
from types import SimpleNamespace

import discord
import pytest

from ttrpg_chatbots.bots.identity import ROLE_FRIEND, BotSpec
from ttrpg_chatbots.bots.permissions import requirements_for
from ttrpg_chatbots.bots.roster import Roster, RosterError
from ttrpg_chatbots.bots.supervisor import (
    Entry,
    FriendBot,
    _run_all,
    build_entries,
    explain_failure,
    run,
)
from ttrpg_chatbots.respond import Answer


class _Client:
    """A stand-in for a Discord client: records what would have happened."""

    def __init__(self, *, fail: BaseException | None = None) -> None:
        self.started: str | None = None
        self.closed = False
        self.runs: list[tuple[str, dict]] = []
        self.fail = fail

    async def start(self, token: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.started = token

    async def close(self) -> None:
        self.closed = True

    def run(self, token: str, **kwargs) -> None:
        self.runs.append((token, kwargs))


def _helper() -> BotSpec:
    return BotSpec(id="ttrpg-bot", role="helper", commands=True)


def _friend(name: str = "friend-a", *, listen: bool = True, reply: str = "off") -> BotSpec:
    return BotSpec(id=name, role="friend", listen=listen, reply=reply)


def _roster(*bots: BotSpec) -> Roster:
    return Roster(tuple(bots))


def test_a_dormant_friend_is_not_started(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN", raising=False)
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN_FILE", raising=False)
    entries = build_entries(
        _roster(_helper(), _friend()),
        helper_token="helper-token",
        create_helper=lambda guild_id: _Client(),
    )
    assert [entry.spec.id for entry in entries] == ["ttrpg-bot"]
    assert "dormant" in caplog.text


def test_a_friend_with_a_token_is_started(monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_FRIEND_A_TOKEN", "friend-token")
    entries = build_entries(
        _roster(_helper(), _friend()),
        helper_token="helper-token",
        create_helper=lambda guild_id: _Client(),
    )
    assert [entry.spec.id for entry in entries] == ["ttrpg-bot", "friend-a"]
    assert isinstance(entries[1].client, FriendBot)


def test_the_helper_is_built_with_the_guild_id() -> None:
    seen = []

    def factory(guild_id):
        seen.append(guild_id)
        return _Client()

    build_entries(_roster(_helper()), helper_token="token", guild_id=42, create_helper=factory)
    assert seen == [42]


def test_no_token_anywhere_is_an_error(monkeypatch) -> None:
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN", raising=False)
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN_FILE", raising=False)
    with pytest.raises(RosterError, match="no bot has a token"):
        build_entries(_roster(_friend()), helper_token="")


def test_a_friend_requests_message_content_only_when_listening() -> None:
    assert FriendBot(_friend(listen=False)).intents.message_content is False
    assert FriendBot(_friend(listen=True)).intents.message_content is True


def test_the_listener_gate_does_not_touch_the_message_when_off() -> None:
    class _Exploding:
        def __getattr__(self, name):
            raise AssertionError(f"on_message inspected {name!r} while listening was off")

    asyncio.run(FriendBot(_friend(listen=False)).on_message(_Exploding()))


def test_an_entry_never_shows_its_token() -> None:
    entry = Entry(spec=_helper(), client=_Client(), token="super-secret")
    assert "super-secret" not in repr(entry)


def test_a_rejected_token_names_the_variable() -> None:
    message = explain_failure(_helper(), discord.LoginFailure("nope"))
    assert "DISCORD_TOKEN" in message
    assert "regenerate" in message


def test_a_missing_privileged_intent_says_where_to_enable_it() -> None:
    message = explain_failure(_friend(), discord.PrivilegedIntentsRequired(0))
    assert "Message Content" in message
    assert "Developer Portal" in message


def test_one_failing_bot_does_not_stop_the_other(caplog) -> None:
    good, bad = _Client(), _Client(fail=RuntimeError("boom"))
    entries = (
        Entry(spec=_helper(), client=good, token="one"),
        Entry(spec=_friend(), client=bad, token="two"),
    )
    asyncio.run(_run_all(entries))

    assert bad.closed is True
    assert good.closed is True  # returned normally, then closed on the way out
    assert "friend-a" in caplog.text
    assert "boom" in caplog.text


def test_a_single_bot_uses_the_blocking_run_path() -> None:
    client = _Client()
    run(
        _roster(_helper()),
        helper_token="helper-token",
        create_helper=lambda guild_id: client,
    )
    assert client.runs == [("helper-token", {"log_handler": None})]


def test_several_bots_go_through_asyncio(monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_FRIEND_A_TOKEN", "friend-token")
    seen = []

    async def fake_run_all(entries):
        seen.extend(entry.spec.id for entry in entries)

    monkeypatch.setattr("ttrpg_chatbots.bots.supervisor._run_all", fake_run_all)
    run(
        _roster(_helper(), _friend()),
        helper_token="helper-token",
        create_helper=lambda guild_id: _Client(),
    )
    assert seen == ["ttrpg-bot", "friend-a"]


def test_the_helper_can_reach_its_friends(monkeypatch) -> None:
    """One process, so /friendcheck reads friend clients directly instead of using IPC."""
    monkeypatch.setenv("TTRPG_FRIEND_A_TOKEN", "friend-token")
    helper = _Client()
    entries = build_entries(
        _roster(_helper(), _friend()),
        helper_token="helper-token",
        create_helper=lambda guild_id: helper,
        create_friend=lambda spec: _Client(),
    )
    assert set(helper.friends) == {"friend-a"}
    assert helper.friends["friend-a"] is entries[1].client


def test_a_roster_without_a_helper_warns(monkeypatch, caplog) -> None:
    monkeypatch.setenv("TTRPG_FRIEND_A_TOKEN", "friend-token")
    run(
        _roster(_friend(listen=False)),
        helper_token="",
        create_helper=lambda guild_id: _Client(),
        create_friend=lambda spec: _Client(),
    )
    assert "no helper" in caplog.text


class _Perm:
    def __init__(self, allowed: set[str]) -> None:
        self._allowed = frozenset(allowed)

    def __getattr__(self, name: str) -> bool:
        return name in self._allowed


class _Chan:
    id = 7
    name = "general"

    def __init__(self, allowed: set[str]) -> None:
        self._allowed = allowed

    def permissions_for(self, member) -> _Perm:
        return _Perm(self._allowed)


class _Guild:
    def __init__(self, channel) -> None:
        self._channel = channel
        self.me = object()

    def get_channel(self, channel_id):
        return self._channel if channel_id == self._channel.id else None


class _Friend(FriendBot):
    """A FriendBot whose guilds are supplied rather than fetched from a gateway."""

    def __init__(self, spec, guild) -> None:
        super().__init__(spec)
        self._guild = guild

    @property
    def guilds(self):
        return (self._guild,)


def test_a_friend_that_is_not_listening_is_not_warned_about_message_content(caplog) -> None:
    """The audit must not nag about an intent this bot deliberately did not request."""
    caplog.set_level(logging.DEBUG)
    spec = BotSpec(id="friend-a", role="friend", listen=False, channels=(7,))
    allowed = {requirement.name for requirement in requirements_for(ROLE_FRIEND)}
    friend = _Friend(spec, _Guild(_Chan(allowed)))

    asyncio.run(friend.check_permissions())

    assert "message_content" not in caplog.text
    assert "checks passed" in caplog.text


def _heard(text: str = "anyone around?", *, bot_author: bool = False):
    return SimpleNamespace(
        author=SimpleNamespace(display_name="Tav", id=5, bot=bot_author),
        channel=SimpleNamespace(name="general", id=7),
        content=text,
        mentions=[],
    )


def test_a_listening_friend_records_what_it_hears() -> None:
    friend = FriendBot(_friend(listen=True))
    asyncio.run(friend.on_message(_heard()))

    assert friend.received == 1
    assert friend.last_message["author"] == "Tav"
    assert friend.last_message["channel"] == "general"
    assert friend.last_message["text"] == "anyone around?"


def test_a_friend_ignores_other_bots() -> None:
    friend = FriendBot(_friend(listen=True))
    asyncio.run(friend.on_message(_heard("beep", bot_author=True)))

    assert friend.received == 0
    assert friend.last_message == {}
    # ...but the delivery is counted, so a probe can tell filtering from a dead gateway.
    assert friend.delivered == 1
    assert friend.last_delivery["bot"] == "yes"
    assert friend.last_delivery["text"] == "beep"


class _Chat:
    """A stand-in for FriendChat: records the question, answers without a dataset."""

    def __init__(
        self,
        *,
        fail: BaseException | None = None,
        tag: str = "social:greeting",
        text: str = "hey back",
    ) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.contexts: list[object] = []
        self.forced: list[str | None] = []
        self.fail = fail
        self.tag = tag
        self.text = text

    def reply(
        self,
        text: str,
        friend: str,
        *,
        speaker: str | None = None,
        context=None,
        addressed: bool = True,
        style=None,
        force_tag=None,
    ):
        self.calls.append((text, friend, speaker))
        self.contexts.append(context)
        self.forced.append(force_tag)
        if self.fail is not None:
            raise self.fail
        return Answer(text=self.text, source=f"reply:{friend}", detail={"tag": self.tag})


@pytest.fixture(autouse=True)
def _memory_dir(tmp_path, monkeypatch):
    """Every friend's memory lives in a temporary directory, never in data/."""
    monkeypatch.setenv("TTRPG_FRIENDS_MEMORY_DIR", str(tmp_path / "friends"))
    return tmp_path / "friends"


_MESSAGE_IDS = itertools.count(1000)


class _MentionedFriend(FriendBot):
    """A FriendBot with a stable user object, so mentions can be tested without a gateway."""

    def __init__(self, spec, *, chat=None, user=None) -> None:
        super().__init__(spec, chat=chat)
        self._fake_user = user or SimpleNamespace(id=1, mention="<@1>", bot=True)

    @property
    def user(self):
        return self._fake_user


def _mention(friend, text: str = "<@1> hey", *, mentioned: bool = True, bot_author=False):
    message = SimpleNamespace(
        id=next(_MESSAGE_IDS),
        author=SimpleNamespace(display_name="Tav", id=5, bot=bot_author),
        channel=SimpleNamespace(name="general", id=7),
        guild=object(),
        content=text,
        mentions=[friend.user] if mentioned else [],
        replies=[],
    )

    async def reply(content: str, mention_author: bool = True) -> None:
        message.replies.append((content, mention_author))

    message.reply = reply
    return message


def test_a_mention_gets_a_reply_as_the_friend() -> None:
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    message = _mention(friend)

    asyncio.run(friend.on_message(message))

    assert chat.calls == [("hey", "friend-a", "Tav")]
    assert message.replies == [("hey back", False)]
    assert friend.replied == 1
    assert friend.last_reply == "hey back"


def test_a_message_that_does_not_mention_the_friend_gets_no_reply() -> None:
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)

    asyncio.run(friend.on_message(_mention(friend, "<@1> hey", mentioned=False)))

    assert chat.calls == []
    assert friend.replied == 0


def test_a_redelivered_message_is_never_answered_twice() -> None:
    # Gateways redeliver events after a resume, and two processes sharing a token each answer
    # once. Either way the reader sees double texts, so the same message id is answered once.
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    message = _mention(friend)

    asyncio.run(friend.on_message(message))
    asyncio.run(friend.on_message(message))

    assert len(message.replies) == 1
    assert chat.calls == [("hey", "friend-a", "Tav")]
    assert friend.replied == 1


def test_two_different_messages_still_get_two_replies() -> None:
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)

    asyncio.run(friend.on_message(_mention(friend, "<@1> hey")))
    asyncio.run(friend.on_message(_mention(friend, "<@1> hey again")))

    assert friend.replied == 2


# --- an invitation, and the memory that keeps it -------------------------------------------


def test_offering_plans_leaves_an_invitation_open() -> None:
    chat = _Chat(tag="social:plans", text="nothin yet. you free?")
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)

    asyncio.run(friend.on_message(_mention(friend, "<@1> doing anything later?")))

    assert friend.memory.pending_plan is True
    assert friend.memory.path.is_file(), "an open invitation must survive a restart"


def test_accepting_the_invitation_confirms_instead_of_agreeing() -> None:
    chat = _Chat(tag="social:agreement", text="sounds good")
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    friend.memory.remember_plan()

    asyncio.run(friend.on_message(_mention(friend, "<@1> yeah sure")))

    assert chat.forced == ["social:confirm"]
    assert friend.memory.pending_plan is False


def test_no_invitation_means_a_plain_agreement() -> None:
    chat = _Chat(tag="social:agreement", text="sounds good")
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)

    asyncio.run(friend.on_message(_mention(friend, "<@1> yeah sure")))

    assert chat.forced == [None]


def test_memory_survives_a_restart() -> None:
    chat = _Chat()
    first = _MentionedFriend(_friend(reply="mention"), chat=chat)
    asyncio.run(first.on_message(_mention(first, "<@1> hey", )))
    first.memory.remember_plan()
    first.memory.save()

    second = _MentionedFriend(_friend(reply="mention"), chat=_Chat())

    assert second.memory.person == "Tav"
    assert second.memory.pending_plan is True


def test_a_friend_with_reply_off_stays_silent() -> None:
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="off"), chat=chat)

    asyncio.run(friend.on_message(_mention(friend)))

    assert chat.calls == []
    assert friend.replied == 0


def test_a_friend_never_replies_to_a_bot() -> None:
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)

    asyncio.run(friend.on_message(_mention(friend, bot_author=True)))

    assert chat.calls == []
    assert friend.replied == 0


def test_a_mention_outside_the_configured_channels_gets_no_reply() -> None:
    chat = _Chat()
    spec = BotSpec(
        id="friend-a", role="friend", listen=True, reply="mention", channels=(999,)
    )
    friend = _MentionedFriend(spec, chat=chat)

    asyncio.run(friend.on_message(_mention(friend)))

    assert chat.calls == []


def test_a_thread_under_a_configured_channel_is_allowed() -> None:
    chat = _Chat()
    spec = BotSpec(
        id="friend-a", role="friend", listen=True, reply="mention", channels=(7,)
    )
    friend = _MentionedFriend(spec, chat=chat)
    message = _mention(friend)
    message.channel = SimpleNamespace(id=555, parent_id=7, name="build-thread")

    asyncio.run(friend.on_message(message))

    assert chat.calls


def test_a_classifier_failure_is_logged_not_raised(caplog) -> None:
    chat = _Chat(fail=RuntimeError("dataset on fire"))
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    message = _mention(friend)

    asyncio.run(friend.on_message(message))

    assert message.replies == []
    assert friend.replied == 0
    assert "cannot answer" in caplog.text or "dataset on fire" in caplog.text


def test_the_greet_ladder_takes_over_only_when_asked(monkeypatch) -> None:
    # TTRPG_CONVERSATION=greet is the switch: with it off the old classifier answers, with it on
    # the ladder answers greetings and leaves everything else to the old path.
    monkeypatch.setenv("TTRPG_CONVERSATION", "greet")
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    message = _mention(friend)

    asyncio.run(friend.on_message(message))

    assert chat.calls == []  # the old path was not consulted
    assert len(message.replies) == 1
    said, _ = message.replies[0]
    assert len(said.split()) <= 3
    assert friend.replied == 1


def test_the_greet_ladder_leaves_non_greetings_to_the_old_path() -> None:
    import os

    os.environ["TTRPG_CONVERSATION"] = "greet"
    try:
        chat = _Chat()
        friend = _MentionedFriend(_friend(reply="mention"), chat=chat)

        asyncio.run(friend.on_message(_mention(friend, "<@1> thanks")))

        assert chat.calls == [("thanks", "friend-a", "Tav")]
    finally:
        os.environ.pop("TTRPG_CONVERSATION", None)


def test_replying_to_his_message_counts_as_talking_to_him() -> None:
    # Discord does not add a mention when you use the reply arrow, so requiring `mentions`
    # silently ignored the most natural way to answer a bot. Reported live: "is he seeing these".
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    message = _mention(friend, "what are you up to", mentioned=False)
    message.reference = SimpleNamespace(resolved=SimpleNamespace(author=friend.user))

    asyncio.run(friend.on_message(message))

    assert chat.calls == [("what are you up to", "friend-a", "Tav")]


def test_replying_to_someone_else_still_counts_as_unaddressed() -> None:
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    message = _mention(friend, "agreed", mentioned=False)
    message.reference = SimpleNamespace(resolved=SimpleNamespace(author=SimpleNamespace(id=99)))

    asyncio.run(friend.on_message(message))

    assert chat.calls == []


def test_a_reply_is_recognised_even_when_the_referenced_message_is_not_resolved() -> None:
    # Discord does not always include the referenced message, and `mentions` holds Member
    # objects while `self.user` is a ClientUser -- so matching ids of what he actually sent is
    # the reliable signal. This is the case that was silently dropping real messages.
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    first = _mention(friend)

    async def reply(content: str, mention_author: bool = True):
        first.replies.append((content, mention_author))
        return SimpleNamespace(id=4242)

    first.reply = reply
    asyncio.run(friend.on_message(first))

    second = _mention(friend, "what are you up to", mentioned=False)
    second.reference = SimpleNamespace(resolved=None, message_id=4242)

    asyncio.run(friend.on_message(second))

    assert [call[0] for call in chat.calls] == ["hey", "what are you up to"]


def test_a_role_ping_is_a_summon() -> None:
    # Typing @TerrysTopGuy autocompletes to the managed role Discord made for the application, so
    # the message arrives as <@&id> with `mentions` empty and `mention_roles` set. That is how a
    # person actually addresses a bot -- every message from the reader looked unaddressed without
    # this, which is why he seemed to be ignoring the channel.
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    role = SimpleNamespace(id=777, managed=True, name="friend-a")
    friend._fake_user = SimpleNamespace(id=1, mention="<@1>", bot=True)
    message = _mention(friend, "<@&777> hey", mentioned=False)
    message.mention_roles = [role]
    message.guild = SimpleNamespace(me=SimpleNamespace(roles=[role]), get_member=lambda _id: None)

    asyncio.run(friend.on_message(message))

    assert chat.calls == [("hey", "friend-a", "Tav")]


def test_an_unrelated_role_ping_is_not_a_summon() -> None:
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)
    other = SimpleNamespace(id=999, managed=True, name="players")
    message = _mention(friend, "<@&999> hey gang", mentioned=False)
    message.mention_roles = [other]
    message.guild = SimpleNamespace(
        me=SimpleNamespace(roles=[SimpleNamespace(id=777, managed=True, name="friend-a")]),
        get_member=lambda _id: None,
    )

    asyncio.run(friend.on_message(message))

    assert chat.calls == []


def test_the_whole_ladder_takes_over_the_phases_it_owns(monkeypatch) -> None:
    # TTRPG_CONVERSATION=ladder answers every phase a friend has a phrasebook for. The old
    # classifier is not consulted for any of them.
    monkeypatch.setenv("TTRPG_CONVERSATION", "ladder")
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)

    for said in ("hey", "what are you up to", "rough day at work", "thanks", "good night"):
        asyncio.run(friend.on_message(_mention(friend, f"<@1> {said}")))

    assert chat.calls == [], "the ladder owned every one of those"
    assert friend.replied == 5


def test_a_knowledge_question_still_goes_to_the_old_path(monkeypatch) -> None:
    # World knowledge is not wired into the ladder yet, so those questions keep the classifier that
    # actually knows something. A downgrade here would be worse than the old behaviour.
    monkeypatch.setenv("TTRPG_CONVERSATION", "ladder")
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)

    asyncio.run(friend.on_message(_mention(friend, "<@1> what is the plot of dune")))

    assert chat.calls == [("what is the plot of dune", "friend-a", "Tav")]


def test_the_greet_only_switch_leaves_the_other_phases_alone(monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_CONVERSATION", "greet")
    chat = _Chat()
    friend = _MentionedFriend(_friend(reply="mention"), chat=chat)

    asyncio.run(friend.on_message(_mention(friend, "<@1> what are you up to")))

    assert chat.calls == [("what are you up to", "friend-a", "Tav")]
