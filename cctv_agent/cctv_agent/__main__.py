"""python -m cctv_agent --config /config/agent.yml"""

import argparse
import asyncio
import logging

from cctv_agent.agent import Agent
from cctv_agent.config import load


def main():
	ap = argparse.ArgumentParser(description="Upande Security CCTV site agent")
	ap.add_argument("--config", default="/config/agent.yml")
	args = ap.parse_args()
	cfg = load(args.config)
	logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
	asyncio.run(Agent(cfg).run())


if __name__ == "__main__":
	main()
