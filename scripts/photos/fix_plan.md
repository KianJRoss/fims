# World Class photo fix plan (DRY-RUN — nothing applied)

- **70 products** would get their image repointed to the file that depicts them (regression-safe: every target is currently MISMATCH or has a missing file)
- 12 conflict losers dropped (a stronger source won the same target)
- 64 duplicate sources need their own photo (their file shows an ALREADY-correct product, so the target was left untouched)
- 41 'orphan source' products still need a fresh photo (their wrong file moved to its rightful product, none arrived for them)
- 137 still unpinned + 23 missing-file: need re-pull/sourcing

Mechanism: `products[target].image_path := source file path`. Files are not moved; reversible via fix_backup.json.

## Repoints (before -> after)

| tier | via | product (gets correct photo) | new image_path | (was) | source file from |
|---|---|---|---|---|---|
| HIGH | SKU+name | 1000443 WHAT A GIRL WANTS | product_images/1003972.png | product_images/1000443.png | 1003972 (MORE FOR YOUR MONEY) |
| HIGH | SKU+name | 1003904 DINO-MIGHT | product_images/1003894.png | product_images/1003904.png | 1003894 (FIRE THIEF) |
| HIGH | SKU+name | 1004102 ROYAL REEFER | product_images/1004118.png | product_images/1004102.png | 1004118 (WATERFALL WONDER) |
| HIGH | SKU+name | 1004104 BUCK WILD | product_images/1004102.png | product_images/1004104.png | 1004102 (ROYAL REEFER) |
| HIGH | SKU+name | 1004269 ALIEN ASCEND | product_images/1004323.png | product_images/1004269.png | 1004323 (MYSTIC WILLOW) |
| HIGH | SKU+name | 1004273 CLAW ENFORCEMENT | product_images/1004270.png | product_images/1004273.png | 1004270 (UNITED FIREWORKS CHAMPION) |
| HIGH | SKU+name | 1004296 FLAMINGO FLING | product_images/1001710.png | product_images/1004296.png | 1001710 (PARACHUTE BATTALION) |
| HIGH | SKU+name | 1004314 GORILLA JAMS | product_images/1004313.png | product_images/1004314.png | 1004313 (They Hate Us) |
| HIGH | SKU+name | 1004315 I IDENTIFY AS A FIREWORK | product_images/1004321.png | product_images/1004315.png | 1004321 (I DONUT CARE) |
| HIGH | SKU+name | 1004317 LOVE IT OR LEAVE IT | product_images/1004318.png | product_images/1004317.png | 1004318 (NEON STRIPES) |
| HIGH | SKU+name | 1004318 NEON STRIPES | product_images/1004317.png | product_images/1004318.png | 1004317 (LOVE IT OR LEAVE IT) |
| HIGH | SKU+name | 1004321 I DONUT CARE | product_images/1004315.png | product_images/1004321.png | 1004315 (I IDENTIFY AS A FIREWORK) |
| HIGH | SKU+name | 1004325 BEAD BANDIT | product_images/1004327.png | product_images/1004325.png | 1004327 (SUNFLOWER DELIGHT) |
| HIGH | SKU+name | 1004327 SUNFLOWER DELIGHT | product_images/1004325.png | product_images/1004327.png | 1004325 (BEAD BANDIT) |
| HIGH | SKU+name | 1004395 GOD BLESS AMERICA | product_images/1003311.png | product_images/1004395.png | 1003311 (ONE BAD GRANNY) |
| HIGH | SKU+name | 1015073 SEXY RIDER | product_images/1015037.png | product_images/1015073.png | 1015037 (One Bad Mother-In-Law) |
| HIGH | SKU+name | 1015406 Breathing | product_images/1015086.png | product_images/1015406.png | 1015086 (ORIENTAL DRAGON) |
| MED | SKU | 1001803 5 BALL BANG | product_images/1001813.png | product_images/1001803.png | 1001813 (M-5000 CRACKLING CANDLE) |
| MED | SKU | 1004270 UNITED FIREWORKS CHAMPION | product_images/1004273.png | product_images/1004270.png | 1004273 (CLAW ENFORCEMENT) |
| MED | SKU | 1011302 FRISKY STARBURST | product_images/1011425.png | product_images/1011302.png | 1011425 (MAMA MIA) |
| NAME | name | 1000108 JET SCREAMER | product_images/1003122.png | product_images/1000108.png | 1003122 (Rapid-) |
| NAME | name | 1000469 TWO FOR THE SHOW | product_images/1000470.png | product_images/1000469.png | 1000470 (THREE TO GET READY) |
| NAME | name | 1000470 THREE TO GET READY | product_images/1000469.png | product_images/1000470.png | 1000469 (TWO FOR THE SHOW) |
| NAME | name | 1000471 FOUR TO GO | product_images/1000458.png | product_images/1000471.png | 1000458 (KILLER VALUE) |
| NAME | name | 1000479 JUNK IN THE TRUNK | product_images/1024420.png | product_images/1000479.png | 1024420 (SHINING SKY) |
| NAME | name | 1000553 JUMBO M-5000 RED | product_images/1000203.png | product_images/1000553.png | 1000203 (M-5000 CRACKER MAX. LOAD 12 COUNT) |
| NAME | name | 1001301 LAND OF FREE | product_images/1001304.png | product_images/1001301.png | 1001304 (COLOR PEARL FLOWER 48 SHOTS) |
| NAME | name | 1001340 GARDEN IN SPRING | product_images/1003107.png | product_images/1001340.png | 1003107 (AMERICAN MUSCLE) |
| NAME | name | 1001416 WHISTLING JAKE | product_images/1001435.png | product_images/1001416.png | 1001435 (PREMIUM ARTILLERY SHELLS) |
| NAME | name | 1001519 STRIKE | product_images/1001508.png | product_images/1001519.png | 1001508 (SIDEWINDER MISSILE) |
| NAME | name | 1001611 CLIMBING PANDA | product_images/1016059.png | product_images/1001611.png | 1016059 (CHICKEN BLOWING BALLOON) |
| NAME | name | 1001653 CRACKLING BALLS | product_images/1002102.png | product_images/1001653.png | 1002102 (GROUND BLOOM FLOWER) |
| NAME | name | 1002227 POOPY PUPPY | product_images/1001653.png | product_images/1002227.png | 1001653 (CRACKLING BALLS) |
| NAME | name | 1003107 AMERICAN MUSCLE | product_images/1001340.png | product_images/1003107.png | 1001340 (GARDEN IN SPRING) |
| NAME | name | 1003110 SHOW OF FORCE | product_images/1003114.png | product_images/1003110.png | 1003114 (HEAVY METAL) |
| NAME | name | 1003119 MADNESS | product_images/1003110.png | product_images/1003119.png | 1003110 (SHOW OF FORCE) |
| NAME | name | 1003294 ULTIMATE WARRIOR | product_images/1013167.png | product_images/1003294.png | 1013167 (Grapes Over Vineyard) |
| NAME | name | 1003314 EVIL PRIEST | product_images/1003130.png | product_images/1003314.png | 1003130 (AMAZING) |
| NAME | name | 1003352 FESTIVAL BALL | product_images/1001413.png | product_images/1003352.png | 1001413 (CRACKLING ARTILLERY SHELL) |
| NAME | name | 1003366 TEQUILA PARTY | product_images/1001309.png | product_images/1003366.png | 1001309 (100 SHOT MAGICAL BARRAGE) |
| NAME | name | 1003380 FAITH OVER FEAR | product_images/1030029.png | product_images/1003380.png | 1030029 (CHASING BOOTY) |
| NAME | name | 1003523 SCREWBALL | product_images/1004137.png | product_images/1003523.png | 1004137 (DO NOT DISTURB) |
| NAME | name | 1003705 LEGENDS NEVER DIE | product_images/1003706.png | product_images/1003705.jpg | 1003706 (BOOTLEGGERS' DREAM) |
| NAME | name | 1003919 TREE FORT | product_images/1004306.png | product_images/1003919.png | 1004306 (WINGS OF FREEDOM) |
| NAME | name | 1003972 MORE FOR YOUR MONEY | product_images/1000442.png | product_images/1003972.png | 1000442 (WHAT BOYS ARE MADE OF) |
| NAME | name | 1003978 ROCK STAR | product_images/1024522.png | product_images/1003978.png | 1024522 (GREAT NIGHT EXTRAVAGANZA) |
| NAME | name | 1004117 PRETTY POISON | product_images/1004135.jpg | product_images/1004117.jpg | 1004135 (FOOTBALL FOUNTAIN) |
| NAME | name | 1004135 FOOTBALL FOUNTAIN | product_images/1004117.jpg | product_images/1004135.jpg | 1004117 (PRETTY POISON) |
| NAME | name | 1004295 OLD GLORY GLIDER | product_images/1001701.png | product_images/1004295.png | 1001701 (7 LANTERN PARACHUTE) |
| NAME | name | 1011303 PIP SQUEAK | product_images/1011416.png | product_images/1011303.png | 1011416 (TASTE THE RAINBOW) |
| NAME | name | 1011377 FROG PRINCE | product_images/1011369.png | product_images/1011377.png | 1011369 (AMIERICAN'S FOUNTAIN) |
| NAME | name | 1011416 TASTE THE RAINBOW | product_images/1011303.png | product_images/1011416.png | 1011303 (PIP SQUEAK) |
| NAME | name | 1011418 GO GIRL GO | product_images/1011365.png | product_images/1011418.png | 1011365 (MESMERIZE) |
| NAME | name | 1011420 FOOL'S GOLD | product_images/1012047.png | product_images/1011420.png | 1012047 (FLIPPIN' AWESOME) |
| NAME | name | 1011458 RIPPLE EFFECT | product_images/1011302.png | product_images/1011458.png | 1011302 (FRISKY STARBURST) |
| NAME | name | 1012047 FLIPPIN' AWESOME | product_images/1011420.png | product_images/1012047.png | 1011420 (FOOL'S GOLD) |
| NAME | name | 1013129 WRECKLESS | product_images/1013177.png | product_images/1013129.png | 1013177 (CRAZY EXCITING) |
| NAME | name | 1013185 One Bad Mother | product_images/1015058.png | product_images/1013185.png | 1015058 (America’s Celebration) |
| NAME | name | 1013187 Extreme Machine | product_images/1013211.png | product_images/1013187.png | 1013211 (GRAVE DIGGER) |
| NAME | name | 1013211 GRAVE DIGGER | product_images/1015039.png | product_images/1013211.png | 1015039 (CRAZY EXCITING ON STEROIDS) |
| NAME | name | 1013223 Not In My Yard | product_images/1013185.png | product_images/1013223.png | 1013185 (One Bad Mother) |
| NAME | name | 1015081 MIDNIGHT SUNBURN | product_images/1015147.png | product_images/1015081.png | 1015147 (GORILLA WARFARE) |
| NAME | name | 1015086 ORIENTAL DRAGON | product_images/1003112.png | product_images/1015086.png | 1003112 (INFERNO PUNCH) |
| NAME | name | 1015123 AMERICAN INTENSITY | product_images/1015081.png | product_images/1015123.png | 1015081 (MIDNIGHT SUNBURN) |
| NAME | name | 1015453 AMERICAN RIDERS | product_images/1013187.png | product_images/1015453.png | 1013187 (Extreme Machine) |
| NAME | name | 1015454 SAY WHAT?? | product_images/1015305.png | product_images/1015454.png | 1015305 (Captain Jake) |
| NAME | name | 1024420 SHINING SKY | product_images/1024515.png | product_images/1024420.png | 1024515 (STAR AND STRIPES) |
| NAME | name | 1024513 THE KING | product_images/1000401.png | product_images/1024513.png | 1000401 (KTNG) |
| NAME | name | 1030002 BUBBLE BLASTER | product_images/1001823.png | product_images/1030002.png | 1001823 (WORLD CLASS 4 ASST. ROMAN CANDLE) |
| NAME | name | 1030038 Bent Rail | product_images/1030035.png | product_images/1030038.png | 1030035 (TANK GIRL) |

## Orphan sources — still need a correct photo

- 1000203 M-5000 CRACKER MAX. LOAD 12 COUNT
- 1000401 KTNG
- 1000442 WHAT BOYS ARE MADE OF
- 1000458 KILLER VALUE
- 1001304 COLOR PEARL FLOWER 48 SHOTS
- 1001309 100 SHOT MAGICAL BARRAGE
- 1001413 CRACKLING ARTILLERY SHELL
- 1001435 PREMIUM ARTILLERY SHELLS
- 1001508 SIDEWINDER MISSILE
- 1001701 7 LANTERN PARACHUTE
- 1001710 PARACHUTE BATTALION
- 1001813 M-5000 CRACKLING CANDLE
- 1001823 WORLD CLASS 4 ASST. ROMAN CANDLE
- 1002102 GROUND BLOOM FLOWER
- 1003112 INFERNO PUNCH
- 1003114 HEAVY METAL
- 1003122 Rapid-
- 1003130 AMAZING
- 1003311 ONE BAD GRANNY
- 1003706 BOOTLEGGERS' DREAM
- 1003894 FIRE THIEF
- 1004118 WATERFALL WONDER
- 1004137 DO NOT DISTURB
- 1004306 WINGS OF FREEDOM
- 1004313 They Hate Us
- 1004323 MYSTIC WILLOW
- 1011365 MESMERIZE
- 1011369 AMIERICAN'S FOUNTAIN
- 1011425 MAMA MIA
- 1013167 Grapes Over Vineyard
- 1013177 CRAZY EXCITING
- 1015037 One Bad Mother-In-Law
- 1015039 CRAZY EXCITING ON STEROIDS
- 1015058 America’s Celebration
- 1015147 GORILLA WARFARE
- 1015305 Captain Jake
- 1016059 CHICKEN BLOWING BALLOON
- 1024515 STAR AND STRIPES
- 1024522 GREAT NIGHT EXTRAVAGANZA
- 1030029 CHASING BOOTY
- 1030035 TANK GIRL
