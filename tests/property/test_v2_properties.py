import asyncio
import gzip
import json
import logging
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio, _SplunkQueue

PROPERTY_SETTINGS = settings(max_examples=40, deadline=None, derandomize=True)
UNICODE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    max_size=40,
)
JSON_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
    UNICODE_TEXT,
)
JSON_VALUES = st.recursive(
    JSON_SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(UNICODE_TEXT, children, max_size=4),
    ),
    max_leaves=12,
)
EVENT = st.builds(
    lambda event, timestamp: {"event": event, "time": timestamp},
    event=JSON_VALUES,
    timestamp=st.integers(min_value=0, max_value=2**31).map(str),
)
EVENTS = st.lists(
    EVENT,
    min_size=1,
    max_size=5,
)


class _RecordingResponse:
    status = 200
    reason = "OK"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def text(self):
        return '{"text":"Success","code":0}'


class _RecordingClientSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _RecordingRetryClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.response

    async def close(self):
        return None


def _post_batch(sender, batch):
    response = _RecordingResponse()
    session = _RecordingClientSession()
    retry_client = _RecordingRetryClient(response)

    async def post():
        work_queue = asyncio.Queue()
        await work_queue.put(batch)
        return await sender._http_post_task(sender.splunk_post_url, work_queue)

    with (
        patch(
            "splunk_hec_aio.splunk_hec_aio.ClientSession",
            return_value=session,
        ),
        patch(
            "splunk_hec_aio.splunk_hec_aio.RetryClient",
            return_value=retry_client,
        ),
    ):
        result = asyncio.run(post())

    assert result == (200, "OK")
    assert len(retry_client.requests) == 1
    return retry_client.requests[0]


@PROPERTY_SETTINGS
@given(events=st.lists(EVENT, max_size=20))
def test_queue_preserves_fifo_order_and_released_size_accounting(events):
    queue = _SplunkQueue(list(events))

    assert queue.size == len(events)
    assert queue.byte_size == (len(json.dumps(events, default=str)) if events else 0)
    if events:
        assert queue.first == events[0]
        assert queue.last == events[-1]

    assert [queue.dequeue() for _ in events] == events
    assert queue.is_empty
    assert queue.dequeue() is None


@PROPERTY_SETTINGS
@given(events=EVENTS)
def test_json_transport_round_trips_bounded_event_batches(events):
    sender = SplunkHecAio("splunk.example", "test-token")
    sender.log.setLevel(logging.CRITICAL)

    _, request = _post_batch(sender, events)
    body = gzip.decompress(request["data"]).decode("utf-8")

    assert body == json.dumps(events)
    assert json.loads(body) == events


@PROPERTY_SETTINGS
@given(
    payloads=st.lists(
        st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            max_size=80,
        ),
        min_size=1,
        max_size=6,
    )
)
def test_raw_transport_concatenates_each_generated_payload_once(payloads):
    sender = SplunkHecAio("splunk.example", "test-token")
    sender.log.setLevel(logging.CRITICAL)
    sender.set_payload_json_format(False)

    _, request = _post_batch(sender, payloads)
    body = gzip.decompress(request["data"]).decode("utf-8")

    assert body == "".join(payloads)


@PROPERTY_SETTINGS
@given(
    messages=st.lists(
        st.text(
            alphabet=st.characters(
                min_codepoint=32,
                max_codepoint=126,
            ),
            min_size=1,
            max_size=1200,
        ),
        min_size=1,
        max_size=10,
    )
)
def test_ascii_batch_boundaries_do_not_lose_or_duplicate_events(messages):
    sender = SplunkHecAio("splunk.example", "test-token")
    sender.log.setLevel(logging.CRITICAL)
    sender.set_pop_empty_fields(False)
    sender.set_post_max_byte_size(4000)
    sender.set_concurrent_post_limit(20)
    events = [{"event": message} for message in messages]

    for event in events:
        sender.post_data(event)

    completed_batches = sender.post_queue.elements
    assert all(completed_batches)
    queued_events = [event for batch in completed_batches for event in batch]
    queued_events.extend(sender.payload_queue.elements)
    assert queued_events == events
