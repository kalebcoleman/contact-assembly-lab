"""Write seeded variants of dog.json whose loose-brick XY positions are jittered."""

import json
from pathlib import Path
from random import Random

from experiments.ur5e_dog.validate import validate

JITTER_M = 0.015


def main() -> None:
    """Write variants/seed_{1..5}.json; each jitters every pickup XY by up to ±15 mm.

    Samples that violate source spacing or plate clearance are redrawn.
    """
    base_path = Path(__file__).with_name("dog.json")
    base = json.loads(base_path.read_text())
    out = Path(__file__).with_name("variants")
    out.mkdir(exist_ok=True)
    for seed in range(1, 6):
        rng = Random(seed)
        while True:
            config = json.loads(json.dumps(base))
            config["experiment_name"] = f"dog_ten_seed{seed}"
            config["brick_positions_xy_m"] = [
                [round(c + rng.uniform(-JITTER_M, JITTER_M), 4) for c in p]
                for p in base["brick_positions_xy_m"]
            ]
            try:
                validate(config)
            except ValueError:
                continue
            break
        (out / f"seed_{seed}.json").write_text(json.dumps(config, indent=2) + "\n")


if __name__ == "__main__":
    main()
