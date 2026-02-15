"""Legacy script wrapper.

This repository previously shipped a single large script `warrants_searcher_v6_fixed_3.py`.
It is kept for backwards compatibility, but the implementation has been refactored
into the `warrant_scanner` package.

Run the new CLI:

  python -m warrant_scanner.main --limit 50 --out top_options.csv

"""

from warrant_scanner.main import main


if __name__ == "__main__":
    main()
