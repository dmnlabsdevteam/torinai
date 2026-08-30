import asyncio
import aiohttp
from aiohttp import web
import logging
from typing import Dict, List, Optional
import nltk
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize
from nltk.corpus import wordnet
import gc
from cachetools import TTLCache
import ujson
from collections import deque
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

#: NLTK resources this module needs, with the path each is found under.
_NLTK_RESOURCES = (
    ("punkt", "tokenizers/punkt"),
    ("punkt_tab", "tokenizers/punkt_tab"),
    ("wordnet", "corpora/wordnet"),
    ("omw-1.4", "corpora/omw-1.4"),
    ("stopwords", "corpora/stopwords"),
)


def ensure_nltk_data() -> Dict[str, bool]:
    """Make sure the corpora are present. Returns what is available.

    THIS RAN AT IMPORT TIME AS THREE UNCONDITIONAL `nltk.download()` CALLS.
    Importing the module therefore made network requests -- every time, even
    when the data was already on disk -- so an import could block or fail on a
    host with no network. Combined with `cachetools` not being installed, the
    module could not be imported at all.

    Checked before fetched, and a failure is reported rather than raised: this
    module is a text utility, and being unable to reach the internet is not a
    reason for importing it to explode.
    """
    available: Dict[str, bool] = {}
    for name, path in _NLTK_RESOURCES:
        try:
            nltk.data.find(path)
            available[name] = True
            continue
        except LookupError:
            pass
        try:
            available[name] = bool(nltk.download(name, quiet=True))
        except Exception as error:
            logger.warning("NLTK resource %r unavailable: %s", name, error)
            available[name] = False
    missing = [n for n, ok in available.items() if not ok]
    if missing:
        logger.warning("NLTK resources missing, text processing will be "
                       "degraded: %s", missing)
    return available


#: Resolved once, on first use, not on import. See ensure_nltk_data.
_nltk_ready: Optional[Dict[str, bool]] = None


def nltk_ready() -> Dict[str, bool]:
    """Resolve the corpora on first use and remember the answer."""
    global _nltk_ready
    if _nltk_ready is None:
        _nltk_ready = ensure_nltk_data()
    return _nltk_ready

class NLPProcessor:
    """
    Process natural language text using a streaming algorithm and NLTK's wordnet.

    Attributes:
        _tokenizer: Tokenizer used for splitting text into words.
        _stop_words: Set of stop words to ignore during processing.
        _word_cache: Cache of wordnet lemmas for efficient lookups.
        _lemmatizer: Lemmatizer for converting words to their base form.
    """

    def __init__(self, tokenizer=None, stop_words=None, cache_dir='.nlp_cache'):
        """
        Initialize the NLP processor.

        Args:
            tokenizer: Tokenizer to use for splitting text. Defaults to None.
            stop_words: Set of stop words to ignore. Defaults to None.
            cache_dir: Directory to cache frequently accessed data. Defaults to '.nlp_cache'.
        """
        self._tokenizer = tokenizer or r'\W+'
        self._stop_words = stop_words or set(nltk.corpus.stopwords.words('english'))
        self._word_cache = TTLCache(maxsize=100, ttl=60)  # Use a TTL cache to reduce memory usage
        self._lemmatizer = WordNetLemmatizer()

    async def process_text(self, text: str) -> List[str]:
        """Lemmatised content words of `text`, lowercased, deduplicated, sorted.

        THREE DEFECTS FIXED HERE, all visible in one call.

        1. IT RETURNED TWO DIFFERENT TYPES. Tokens were cached as a list and
           `ujson.dumps(...)` was returned, so a cache MISS returned a JSON
           string and a cache HIT returned a list -- from the same function,
           annotated `-> List[str]`. A caller iterating the result got
           characters the first time and words the second.
        2. CASE WAS NOT NORMALISED, so `Copper` and `copper` were two tokens
           and a word never matched itself across a sentence boundary.
        3. The docstring carried self-improvement commentary ("This is a
           temporary fix to address the gap identified in the NLP optimizer")
           instead of describing the function.

        This is text NORMALISATION, not understanding. The substrate reads
        sentences through `core.semantics` -- a derived reading procedure over
        a sentence machine -- and nothing in that path uses this. Use it for
        bag-of-words work: matching, indexing, coarse similarity.
        """
        if not text:
            raise ValueError("Input text cannot be empty")

        cached = self._word_cache.get(text)
        if cached is not None:
            return list(cached)

        tokens = set()
        for word in word_tokenize(text):
            lowered = word.lower()
            if lowered in self._stop_words or not lowered.isalnum():
                continue
            tokens.add(self._lemmatizer.lemmatize(lowered))

        result = sorted(tokens)
        # Cache a copy and return a copy, so a caller mutating the result
        # cannot corrupt what the next caller receives.
        self._word_cache[text] = list(result)
        return result


class NLPProcessorPool:
    """
    Process natural language text using a streaming algorithm and NLTK's wordnet in parallel.

    Attributes:
        _processors: List of NLP processors.
    """

    def __init__(self, num_workers=5):
        """
        Initialize the NLP processor pool.

        Args:
            num_workers: Number of workers to use. Defaults to 5.
        """
        self._processors = [NLPProcessor() for _ in range(num_workers)]

    async def process_text(self, text: str) -> List[str]:
        """
        Process the given text using the NLP processor pool.

        Args:
            text: Text to process.

        Returns:
            List: List of processed words.

        Raises:
            ValueError: If the input text is empty.
        """
        if not text:
            raise ValueError("Input text cannot be empty")

        # WORK WAS DUPLICATED, NOT DIVIDED. The nested loop handed EVERY chunk
        # to EVERY processor -- workers x chunks tasks -- so a pool of five did
        # five times the work and returned each token five times. Combined with
        # process_text returning a JSON string, the flattening below then
        # iterated that string CHARACTER BY CHARACTER: the measured output for
        # "the geese were flying" was ['[', '"', 'f', 'l', 'y', ...], repeated
        # once per worker.
        #
        # Chunks are dealt round-robin across the processors instead, which is
        # what a pool is for.
        chunks = self._split(text, self.CHUNK_CHARS)
        if not chunks:
            return []

        tasks = [
            asyncio.create_task(
                self._processors[i % len(self._processors)].process_text(chunk))
            for i, chunk in enumerate(chunks)
        ]
        results = await asyncio.gather(*tasks)

        merged = set()
        for result in results:
            merged.update(result)
        return sorted(merged)

    #: Chunk size in characters; longer text is split across the pool.
    CHUNK_CHARS = 1000

    @staticmethod
    def _split(text: str, size: int) -> List[str]:
        """Split on whitespace boundaries so no chunk cuts a word in half.

        The previous slicing was `text[i:i+1000]`, which can land mid-word and
        hand each half to the lemmatiser as its own token.
        """
        chunks, current, length = [], [], 0
        for word in text.split():
            if current and length + len(word) + 1 > size:
                chunks.append(" ".join(current))
                current, length = [], 0
            current.append(word)
            length += len(word) + 1
        if current:
            chunks.append(" ".join(current))
        return chunks

class MessageQueue:
    """
    A priority queue to handle incoming messages.
    """

    def __init__(self):
        """
        Initialize the message queue.
        """
        self.queue = []

    def put(self, message):
        """
        Put a message into the queue.

        Args:
            message: Message to put into the queue.
        """
        heapq.heappush(self.queue, message)

    def get(self):
        """
        Get a message from the queue.

        Returns:
            Message from the queue.
        """
        return heapq.heappop(self.queue)

class MessageProcessor:
    """
    Process messages from the message queue.
    """

    def __init__(self):
        """
        Initialize the message processor.
        """
        self.queue = MessageQueue()
        self.cache = TTLCache(maxsize=100, ttl=60)  # Use a TTL cache to reduce memory usage
        self._pool = ThreadPoolExecutor(max_workers=5)  # Use a thread pool for parallel processing

    def shutdown(self):
        """Shut down the thread pool executor cleanly to avoid leaked semaphore warnings."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def __del__(self):
        self.shutdown()

    async def process_message(self, message: str) -> List[str]:
        """
        Process the given message.

        Args:
            message: Message to process.

        Returns:
            List: List of processed words.

        Raises:
            ValueError: If the input message is empty.
        """
        if not message:
            raise ValueError("Input message cannot be empty")

        if message in self.cache:
            return self.cache[message]

        result = await self._process_message_parallel(message)
        self.cache[message] = result  # Cache the result
        return result

    async def _process_message_parallel(self, message: str) -> List[str]:
        """
        Process the given message in parallel using the thread pool.

        Args:
            message: Message to process.

        Returns:
            List: List of processed words.
        """
        loop = asyncio.get_running_loop()
        pool = self._pool
        if pool is None:
            self._pool = ThreadPoolExecutor(max_workers=5)
            pool = self._pool
        chunks = [message[i:i+1000] for i in range(0, len(message), 1000)]
        tasks = []
        for chunk in chunks:
            task = loop.run_in_executor(pool, self._process_text, chunk)
            tasks.append(task)
        results = await asyncio.gather(*tasks)
        return [word for result in results for word in result]

    def _process_text(self, text: str) -> List[str]:
        """
        Process the given text using the NLPProcessor.

        Args:
            text: Text to process.

        Returns:
            List: List of processed words.
        """
        processor = NLPProcessor()
        return processor.process_text(text)

async def handle_request(request):
    """
    Handle incoming requests.

    Args:
        request: Request to handle.

    Returns:
        Response to the request.
    """
    text = await request.text()
    processor = MessageProcessor()
    result = await processor.process_message(text)
    return web.json_response({"message": "Message processed successfully", "result": result})

async def process_text_parallel(text: str) -> bytes:
    """
    Process the given text using the NLPProcessorPool in parallel.

    Args:
        text: Text to process.

    Returns:
        bytes: Serialized list of processed words.

    Raises:
        ValueError: If the input text is empty.
    """
    pool = NLPProcessorPool()
    result = await pool.process_text(text)
    return ujson.dumps(result).encode('utf-8')

async def handle_request_binary(request):
    """
    Handle incoming requests.

    Args:
        request: Request to handle.

    Returns:
        Response to the request.
    """
    text = await request.text()
    processor = MessageProcessor()
    result = await processor.process_message(text)
    return web.json_response({"message": "Message processed successfully", "result": result})

# Improved process_message function
class MessageProcessorImproved(MessageProcessor):
    async def process_message(self, message: str) -> List[str]:
        """
        Process the given message.

        Args:
            message: Message to process.

        Returns:
            List: List of processed words.

        Raises:
            ValueError: If the input message is empty.
        """
        if not message:
            raise ValueError("Input message cannot be empty")

        if message in self.cache:
            return self.cache[message]

        task = asyncio.create_task(self._process_message_parallel(message))
        result = await task
        self.cache[message] = result  # Cache the result
        return result