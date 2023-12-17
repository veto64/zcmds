"""askai - ask openai for help"""


# pylint: disable=all
# mypy: ignore-errors

import argparse
import atexit
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Optional

from zcmds.cmds.common.openaicfg import create_or_load_config, save_config
from zcmds.util.prompt_input import prompt_input
from zcmds.util.streaming_console import StreamingConsole

try:
    from zcmds.util.chatgpt import (
        ADVANCED_MODEL,
        AI_ASSISTANT_AS_PROGRAMMER,
        FAST_MODEL,
        SLOW_MODEL,
        ChatCompletion,
        ChatGPTAuthenticationError,
        ChatGPTConnectionError,
        ChatGPTRateLimitError,
        ai_query,
    )
except KeyboardInterrupt:
    # Importing openai stuff can take a while and so if a keyboard interrupt
    # happens during that time then we want to exit immediately rather
    # than throw a cryptic error and stack trace.
    sys.exit(1)


FORCE_COLOR = False


@dataclass
class FileOutputStream:
    outfile: Optional[str] = None

    def write(self, text: str) -> None:
        if self.outfile:
            with open(self.outfile, "a") as f:
                f.write(text)


class OutStream:
    def __init__(self, outfile: Optional[str]) -> None:
        self.outfile = FileOutputStream(outfile)
        self.color_term = StreamingConsole()
        if FORCE_COLOR:
            self.color_term.force_color()

    def write(self, text: str) -> None:
        self.outfile.write(text)
        self.color_term.update(text)

    def close(self) -> None:
        pass


def install_aider_if_missing() -> None:
    """Installs aider to it's own virtual environment using pipx"""
    bin_path = os.path.expanduser("~/.local/bin")
    os.environ["PATH"] = os.environ["PATH"] + os.pathsep + bin_path
    if shutil.which("aider") is not None:
        return
    print("Installing aider...")
    os.system("pipx install aider-chat")
    assert shutil.which("aider") is not None, "aider not found after install"


def parse_args() -> argparse.Namespace:
    argparser = argparse.ArgumentParser(usage="Ask OpenAI for help with code")
    argparser.add_argument("prompt", help="Prompt to ask OpenAI", nargs="?")
    argparser.add_argument("--json", help="Print response as json", action="store_true")
    argparser.add_argument("--set-key", help="Set OpenAI key")
    argparser.add_argument("--output", help="Output file")
    argparser.add_argument("--color", help="Output color", action="store_true")

    model_group = argparser.add_mutually_exclusive_group()
    model_group.add_argument(
        "--fast",
        action="store_true",
        default=False,
        help=f"chat gpt 3 turbo: {FAST_MODEL}",
    )
    model_group.add_argument(
        "--slow", action="store_true", default=False, help=f"chat gpt 4: {SLOW_MODEL}"
    )
    model_group.add_argument(
        "--advanced",
        action="store_true",
        default=False,
        help=f"bleeding edge model: {ADVANCED_MODEL}",
    )
    model_group.add_argument("--model", default=None)
    argparser.add_argument("--verbose", action="store_true", default=False)
    argparser.add_argument("--no-stream", action="store_true", default=False)
    # max tokens
    argparser.add_argument(
        "--max-tokens", help="Max tokens to return", type=int, default=None
    )
    argparser.add_argument(
        "--code",
        action="store_true",
        default=False,
        help="Code mode: enables aider mode",
    )
    return argparser.parse_args()


def cli() -> int:
    args = parse_args()

    global FORCE_COLOR
    FORCE_COLOR = args.color
    config = create_or_load_config()
    model_unspecified = (
        not args.fast and not args.slow and not args.advanced and not args.model
    )
    max_tokens = args.max_tokens
    if args.fast:
        args.model = FAST_MODEL
    if args.model is None:
        if args.slow:
            model = SLOW_MODEL
            if max_tokens is None:
                max_tokens = 4096
        elif args.advanced:
            model = ADVANCED_MODEL
            max_tokens = 128000
        else:
            model = FAST_MODEL
            max_tokens = 4096
    else:
        model = args.model

    if args.code:
        install_aider_if_missing()
        openai_key = config.get("openai_key")
        if openai_key is None:
            print("OpenAI key not found, please set one with --set-key")
            return 1
        if not model_unspecified:
            os.environ["AIDER_MODEL"] = model
        else:
            os.environ["AIDER_MODEL"] = ADVANCED_MODEL
        print(f"Starting aider with model {os.environ['AIDER_MODEL']}")
        os.environ["OPENAI_API_KEY"] = openai_key
        return os.system("aider --no-auto-commits")

    if args.set_key:
        config["openai_key"] = args.set_key
        save_config(config)
    elif "openai_key" not in config:
        key = input("No OpenAi key found, please enter one now: ")
        config["openai_key"] = key
        save_config(config)
    key = config["openai_key"]
    interactive = not args.prompt
    if interactive:
        print(
            "\nInteractive mode - press return three times to submit your code to OpenAI"
        )
    prompt = args.prompt or prompt_input()
    as_json = args.json

    def log(*pargs, **kwargs):
        if not args.verbose:
            return
        print(*pargs, **kwargs)

    log(prompt)
    prompts = [prompt]

    output_stream = OutStream(args.output)
    atexit.register(output_stream.close)

    while True:
        # allow exit() and exit to exit the app
        if prompts[-1].strip().replace("()", "") == "exit":
            print("Exited due to 'exit' command")
            break
        if not as_json:
            print("############ OPEN-AI QUERY")
        try:
            response: ChatCompletion = ai_query(
                openai_key=key,
                prompts=prompts,
                max_tokens=max_tokens,
                model=model,
                ai_assistant_prompt=AI_ASSISTANT_AS_PROGRAMMER,
            )
        except ChatGPTConnectionError as err:
            print(err)
            return 1
        except ChatGPTAuthenticationError as e:
            print(
                "Error authenticating with OpenAI, deleting password from config and exiting."
            )
            print(e)
            save_config({})
            return 1
        except ChatGPTRateLimitError:
            print("Rate limit exceeded, set a new key with --set-key")
            return 1
        if as_json:
            print(response)
            return 0
        if response is None or not response.response.is_success:
            print("No error response recieved from from OpenAI, response was:")
            # output(response, args.output)
            output_stream.write(response)
            return 1
        if not args.output:
            print("############ OPEN-AI RESPONSE\n")
        response_text = ""
        for event in response:
            choice = event.choices[0]
            delta = choice.delta
            event_text = delta.content
            if event_text is None:
                break
            response_text += event_text
            if not args.no_stream:
                output_stream.write(response_text)

        output_stream.write(response_text + "\n")
        prompts.append(response_text)
        if not interactive:
            break
        prompts.append(prompt_input())
    return 0


def main() -> int:
    try:
        return cli()
    except KeyboardInterrupt:
        return 1


if __name__ == "__main__":
    sys.argv.append("write binary search in python")
    sys.argv.append("--code")
    sys.exit(main())
