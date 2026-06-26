# World Class photo fix plan (DRY-RUN — nothing applied)

- **20 products** would get their image repointed to the file that depicts them (regression-safe: every target is currently MISMATCH or has a missing file)
- 3 conflict losers dropped (a stronger source won the same target)
- 19 duplicate sources need their own photo (their file shows an ALREADY-correct product, so the target was left untouched)
- 11 'orphan source' products still need a fresh photo (their wrong file moved to its rightful product, none arrived for them)
- 215 still unpinned + 25 missing-file: need re-pull/sourcing

Mechanism: `products[target].image_path := source file path`. Files are not moved; reversible via fix_backup.json.

## Repoints (before -> after)

| tier | via | product (gets correct photo) | new image_path | (was) | source file from |
|---|---|---|---|---|---|
| HIGH | SKU+name | 1000443 WHAT A GIRL WANTS | product_images/1000442.png | product_images/1003972.png | 1003972 (MORE FOR YOUR MONEY) |
| HIGH | SKU+name | 1003904 DINO-MIGHT | product_images/1003894.png | product_images/1003894.png | 1003894 (FIRE THIEF) |
| HIGH | SKU+name | 1004102 ROYAL REEFER | product_images/1004118.png | product_images/1004118.png | 1004118 (WATERFALL WONDER) |
| HIGH | SKU+name | 1004104 BUCK WILD | product_images/1004118.png | product_images/1004102.png | 1004102 (ROYAL REEFER) |
| HIGH | SKU+name | 1004269 ALIEN ASCEND | product_images/1004323.png | product_images/1004323.png | 1004323 (MYSTIC WILLOW) |
| HIGH | SKU+name | 1004273 CLAW ENFORCEMENT | product_images/1004273.png | product_images/1004270.png | 1004270 (UNITED FIREWORKS CHAMPION) |
| HIGH | SKU+name | 1004296 FLAMINGO FLING | product_images/1001710.png | product_images/1001710.png | 1001710 (PARACHUTE BATTALION) |
| HIGH | SKU+name | 1004314 GORILLA JAMS | product_images/1004313.png | product_images/1004313.png | 1004313 (They Hate Us) |
| HIGH | SKU+name | 1004315 I IDENTIFY AS A FIREWORK | product_images/1004315.png | product_images/1004321.png | 1004321 (I DONUT CARE) |
| HIGH | SKU+name | 1004317 LOVE IT OR LEAVE IT | product_images/1004317.png | product_images/1004318.png | 1004318 (NEON STRIPES) |
| HIGH | SKU+name | 1004318 NEON STRIPES | product_images/1004318.png | product_images/1004317.png | 1004317 (LOVE IT OR LEAVE IT) |
| HIGH | SKU+name | 1004321 I DONUT CARE | product_images/1004321.png | product_images/1004315.png | 1004315 (I IDENTIFY AS A FIREWORK) |
| HIGH | SKU+name | 1004325 BEAD BANDIT | product_images/1004325.png | product_images/1004327.png | 1004327 (SUNFLOWER DELIGHT) |
| HIGH | SKU+name | 1004327 SUNFLOWER DELIGHT | product_images/1004327.png | product_images/1004325.png | 1004325 (BEAD BANDIT) |
| HIGH | SKU+name | 1004395 GOD BLESS AMERICA | product_images/1003311.png | product_images/1003311.png | 1003311 (ONE BAD GRANNY) |
| HIGH | SKU+name | 1015073 SEXY RIDER | product_images/1015037.png | product_images/1015037.png | 1015037 (One Bad Mother-In-Law) |
| HIGH | SKU+name | 1015406 Breathing | product_images/1003112.png | product_images/1015086.png | 1015086 (ORIENTAL DRAGON) |
| MED | SKU | 1001803 5 BALL BANG | product_images/1001813.png | product_images/1001813.png | 1001813 (M-5000 CRACKLING CANDLE) |
| MED | SKU | 1004270 UNITED FIREWORKS CHAMPION | product_images/1004270.png | product_images/1004273.png | 1004273 (CLAW ENFORCEMENT) |
| MED | SKU | 1011302 FRISKY STARBURST | product_images/1011425.png | product_images/1011425.png | 1011425 (MAMA MIA) |

## Orphan sources — still need a correct photo

- 1001710 PARACHUTE BATTALION
- 1001813 M-5000 CRACKLING CANDLE
- 1003311 ONE BAD GRANNY
- 1003894 FIRE THIEF
- 1003972 MORE FOR YOUR MONEY
- 1004118 WATERFALL WONDER
- 1004313 They Hate Us
- 1004323 MYSTIC WILLOW
- 1011425 MAMA MIA
- 1015037 One Bad Mother-In-Law
- 1015086 ORIENTAL DRAGON
