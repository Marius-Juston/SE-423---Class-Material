# UIUC SE 423: Introduction to Mechatronics (Spring 2026) 
[![Build LaTeX PDFs (TeX Live 2025) and Deploy](https://github.com/Marius-Juston/SE-423---Class-Material/actions/workflows/build-latex.yml/badge.svg)](https://github.com/Marius-Juston/SE-423---Class-Material/actions/workflows/build-latex.yml)

This repository is meant to act as a place where all the course material for University of Illinois Urbana-Champaign's SE 423 course will be stored, compiled and shown.

While the work makes use of LaTeX, students are NOT required to use LaTeX to submit thier content (though I would highly recommend you learning to use it!)

## Usage / Contributions

If you are a professor you are of course welcome to use the content from here your purposes! 

You can always do a pull request to eithe repo if you want to enhance the content! Of course, I would love it if you email me (marius.juston@hotmail.fr or mjuston2@illinois.edu ) to tell me you are using my material, it is always interesting to know that other people are using your stuff and what for!  

**If not stated any picture / video is taken / recreated from Wikipedia**

**Unless stated otherwise any circuit diagram is taken the [F28379D Full Reference](https://coecsl.ece.illinois.edu/se423/tms320f28379D_TechRefi.pdf)**

## Resources

### Animations

The animations creation is available in the following repo: https://github.com/Marius-Juston/SE423Animations and are posted in the following YouTube channel https://www.youtube.com/playlist?list=PLc6LuUpXlDnnyZrtYWuCMLDYuijEMPsBh

### Template

#### Color Scheme

The color scheme follows [UIUC branding guidelines](https://brand.illinois.edu/visual-identity/color)

#### Powerpoint 

The powerpoint template was derived from [UIUC PowerPoint Template Library](https://brand.illinois.edu/resources/downloads) 

### RegEx

Useful regex for improve the LaTeX documents


|                 Regex                |       Replacement   |
|:------------------------------------:|:-------------------:|
|                 `->`                 | ` $rightarrow$ `    |
|              `^\d+\.\s+`             |     `\item `        |
|         `(\n\s*){2,}\\begin`         |   `\n%\n\begin`     |
|           `\\\\\s*\n\\end`           |     `\n\end`        |
|     `\\end\{([\w*]+)\}\n(\n\s*)+`    |  `\end{$1}\n%\n`    |
| `([a-zA-Z.?!0-9]) {2,}([a-zA-Z0-9])` |      `$1 $2`        |
| `\\begin\{minted\}\n\[(.*\n)+?\]\n+?`| `\begin{minted}`    |
| `\\begin\{figure\}(\[[a-zA-Z!]+\])?` | `\begin{figure}[H]` |
| `\\begin\{subfigure\}(\[[a-zA-Z!]+\])?` | `\begin{subfigure}[b]` |


## Notes to professors

## L5

- Lecture on ADCs could be increased and spent more time on since it is short and students have a lot of confusion on this. 
- It was not planned but the lecture as it currently stand is only 30 minutes long. It should definitively be increased in length!
- Ideally would be good to have additional process flow diagram or something to explain the relationship between ADC SOC trigger, ADC SOC Chanel, the actual ADC Chip, and then the process of a trigger happening with the ePWM. 
- Students get confused on this and is important for them to understand properlly. 

## L6-7

- Students get confused with the SPI Polarity and Phase, the best way is not necessarily to look at the giure provided in slide 49
- the best way is to looking at an actual diagram and noticing where for the bits where the data is transmitted so that that you know if you clock if reading / writing on the rising edge or the falling edge

## L17

- Talk about HSL instead of HSV (don't know why I didn't do that in the first place)
- You can show the [Color Space](https://marius-juston.github.io/SE-423---Class-Material/color_spaces.html) website that "I" made 
- You can also add details for blob filter, shape filtering, area filtering, etc. since I forgot to add those
- Be careful since you run out of time, be sure to show the blob detection algorithm a little earlier

## L19 Extra

- the Dubins & Reeds-Sheep vizualization is not correct