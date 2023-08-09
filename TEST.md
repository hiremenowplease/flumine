# Development Task

[Repository](https://github.com/hiremenowplease/flumine)  
Instructions: TEST.md

### Set Up

- Clone the repository to your local machine
- install the dependencies with poetry.
- Checkout the `dev` branch and create a NEW branch from it with your name.

### Bug Fix

Your manager has reported a bug with a broken [worker](https://betcode-org.github.io/flumine/workers/) in the [repository](https://github.com/hiremenowplease/flumine) on the `dev` branch. 

- Locate the broken test. Do not change any of the code in the tests.
- Implement the `update_exposure_settings` method so that the tests passes - you will need to use `get_remote_exposures` to get the updated exposure settings.
- Commit your code.

### Trading Controls

You own a horse that is in an upcoming race, new Australian legislation states that you are not legally allowed to place a limit on close bet on your horse.  The upcoming race that your horse is racing in has the following details:

```
market_id: 1.23456789
selection_id: 99999999
```
- Implement a risk control that ensures you cannot bet on your own runner.
- The risk controls can be found in `tradingcontrols.py` and will need to be wired up somehow.
- Ensure you log that you are skipping the bet when this control is triggered.
