"""Interacts with open ai's chat bot."""


# pylint: disable=all
# mypy: ignore-errors

import sys
import threading
from collections import defaultdict

import json5 as json
import tiktoken

try:
    import openai
    from openai import APIConnectionError, AuthenticationError, OpenAI

except KeyboardInterrupt:
    sys.exit(1)


MAX_TOKENS = 4096
HIDDEN_PROMPT_TOKEN_COUNT = (
    100  # this hack corrects for the unnaccounted for tokens in the prompt
)
ADVANCED_MODEL = "gpt-4-1106-preview"
SLOW_MODEL = "gpt-4"
FAST_MODEL = "gpt-3.5-turbo"
AI_ASSISTANT_AS_PROGRAMMER = (
    "You are a helpful assistant to a senior programmer. "
    "If I am asking how to do something in general then go ahead "
    "and recommend popular third-party apps that can get the job done, "
    "but don't recommend additional tools when I'm currently asking how to do use "
    "a specific tool."
)


class ChatGPTConnectionError(APIConnectionError):
    pass


class ChatGPTAuthenticationError(AuthenticationError):
    pass


class ChatGPTRateLimitError(openai.RateLimitError):
    pass


ChatCompletion = openai.ChatCompletion


# Create a thread-safe dictionary to store OpenAI client instances
client_instances_lock = threading.Lock()
client_instances = defaultdict(lambda: None)


def get_client_instance(openai_key: str) -> OpenAI:
    with client_instances_lock:
        if client_instances[openai_key] is None:
            client_instances[openai_key] = OpenAI(api_key=openai_key)
        return client_instances[openai_key]


def count_tokens(model: str, text: str):
    # Ensure you have the right model, for example, "gpt-3.5-turbo"
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(text))


def ai_query(
    openai_key: str,
    prompts: list[str],
    max_tokens: int,
    model: str,
    ai_assistant_prompt: str,
) -> ChatCompletion:
    # assert prompts is odd
    assert (
        len(prompts) % 2 == 1
    )  # Prompts alternate between user message and last response
    messages = [
        {
            "role": "system",
            "content": ai_assistant_prompt,
        },
    ]
    for i, prompt in enumerate(prompts):
        if i % 2 == 0:
            messages.append({"role": "assistant", "content": prompt})
        else:
            messages.append({"role": "user", "content": prompt})

    # Use the get_client_instance function to ensure thread safety
    client = get_client_instance(openai_key)

    # compute the max_tokens by counting the tokens in the prompt
    # and subtracting that from the max_tokens
    messages_json_str = json.dumps(messages)
    prompt_tokens = count_tokens(model, messages_json_str)
    max_tokens = max_tokens - prompt_tokens - HIDDEN_PROMPT_TOKEN_COUNT
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=max_tokens,
            top_p=0.3,
            frequency_penalty=0.5,
            presence_penalty=0,
            stream=True,
        )
        return response
    except APIConnectionError as e:
        raise ChatGPTConnectionError(e)
    except AuthenticationError as e:
        raise ChatGPTAuthenticationError(e)


class ChatBot:
    def __init__(
        self, openai_key: str, model: str, max_tokens: int, ai_assistant_prompt: str
    ):
        self.openai_key = openai_key
        self.model = model
        self.prompts = []
        self.max_tokens = max_tokens
        self.ai_assistant_prompt = ai_assistant_prompt

    def query(self, prompts: list[str]) -> ChatCompletion:
        return ai_query(
            openai_key=self.openai_key,
            prompts=prompts,
            max_tokens=self.max_tokens,
            model=self.model,
            ai_assistant_prompt=self.ai_assistant_prompt,
        )
