import logging, sys
from newshouse.cli import main
logging.basicConfig(level=logging.DEBUG, filename="out/tick-debug.log", filemode="a", format="%(asctime)s %(name)s %(levelname)s %(message)s")
for noisy in ("httpx", "httpcore", "urllib3", "fastembed", "trafilatura", "filelock", "huggingface_hub"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
sys.argv = ["newshouse", "tick", "--out", "out"]
main()
