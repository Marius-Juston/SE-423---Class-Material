# UIUC SE 423: Introduction to Mechatronics (Spring 2026) 
[![Build LaTeX PDFs (TeX Live 2025) and Deploy](https://github.com/Marius-Juston/SE-423---Class-Material/actions/workflows/build-latex.yml/badge.svg)](https://github.com/Marius-Juston/SE-423---Class-Material/actions/workflows/build-latex.yml)

This repository is meant to act as a place where all the course material for University of Illinois Urbana-Champaign's SE 423 course will be stored, compiled and shown.

While the work makes use of LaTeX, students are NOT required to use LaTeX to submit thier content (though I would highly recommend you learning to use it!)

## Usage / Contributions

If you are a professor you are of course welcome to use the content from here your purposes! 

You can always do a pull request to eithe repo if you want to enhance the content! Of course, I would love it if you email me (marius.juston@hotmail.fr or mjuston2@illinois.edu ) to tell me you are using my material, it is always interesting to know that other people are using your stuff and what for!  

**If not stated any picture / video is taken / recreated from Wikipedia**

**Unless stated otherwise any circuit diagram is taken the [F28379D Full Reference](https://coecsl.ece.illinois.edu/se423/tms320f28379D_TechRefi.pdf)**

The TAs and the instructors should make use of a Master Google Sheet https://docs.google.com/spreadsheets/d/1EjXK2MJgzjrd5-wEUsCvaBVAg1YNXNx1oO10wNDdHqI/edit?usp=sharing 

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


## Accessibility

To ensure compliance with UIUC's new accessibility initiaitive, please make sure that you follow the guide and instructions from https://uofi.app.box.com/s/yabddvw7vb7rpo88cl1amr9reygvbyyr

Especially look at this now: https://aelira.ai/us/blog/how-to-make-latex-accessible
And for the website: https://wave.webaim.org/report#/https://marius-juston.github.io/SE-423---Class-Material/

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

## L20-21

### L20
- The spacing for the lecture I made is horrible, making it very confusing.
- A complete rewrite to show the flow better could be a good idea The pictures are good though.

### L21
- The lecture ended up short about 20 minutes, you can increase the length of the lecture

- you could add Lie Algebra Kalman filters
- you could go into the homework? You could implement different sensor math? Questions?  

### L22-23 & L24-25
- Instead of doing L22-23 focus instead instead for the SLAM lectures (L24-25) since there is a LOT of content to be covered
- The SLAM will be more applicable than the Computer Vision stuff anyways

# Things that I want to add

## Autograder
An auto grader for the course code so that the students can verify that everything is correct even if the TAs / instructors miss something. This has been started at https://github.com/Marius-Juston/AutomaticGrader

## AutoSpreadsheet uploader

Currently the TAs and the instructors make use of a Master Google Sheet https://docs.google.com/spreadsheets/d/1EjXK2MJgzjrd5-wEUsCvaBVAg1YNXNx1oO10wNDdHqI/edit?usp=sharing 

I want to make it so that you can automatically have a cron job that automatically uploads the Google Sheet to Canvas

Also there are some things that could be fixed / improved inside the sheet, such as combining the excerises that are split into multiple weeks still into a single sheet but different columns

# Student Feedback

## 2026

(response count 7, from people that usually came to lectures)
(I removed personal comments about my specific style and paraphrased it where necessary to keep the comments more private and general)

### What aspects of the course design and/or delivery most benefitted your learning?
 - Having plenty of visual examples of algorithms and code–following was extremely helpful throughout the course. Being able to visualize how things like Djikstra's algorithm works allowed me to comprehend them in a lecture setting despite not learning well from lectures, and in past classes having to teach myself similar content.
 - how the lectures better explained topics that were talked about in labs (the connection)
 - The challenges in the laboratory experiments and homework assignments while being able to use lab equipment and our very own electronic components most benefited my learning.
 - It being a lab based course. Had applications to apply material learned.

### What change to the course design or delivery would most benefit your learning?
 - Maybe having the lectures on Zoom since the lectures being at 9 AM meant going to lectures was hard
 – the lecture side of this class is very nice! I think some slight reorganization might be helpful (ie. they found SLAM very interesting but we've spent very little time on it despite its complexity)
 - the lecture that is given before lab (Dan's lectures) could be given during lecture times
 - Perhaps the course is not intended for fully beginners, but a little simplified/"for–dummies" descriptions of the material would've assisted in my learning, as someone with no prior experience in mechatronics besides Python coding.
 - Add quizzes or exams to the course. It is a little too easy right now and doesn't incentivize attending lectures at all
 - Condense some lecture slides content. Less words on each slide. The diagrams you showed were great!

### What recommendations would you give to future students of this course?
 - It is so much fun and you learn SO MUCH. Best choice for a design elective, don't wait till day of to do homework unless you have a lot of prior C knowledge.
 - Go to lectures. Even if they are on the earlier end. I'd also recommend starting the homework earlier rather than later, so that you may visit one of the less busy office hours as opposed to the busiest ones right before homework is due. Make time to go to office hrs to ask questions
 - Even if you are a beginner to mechatronics or believe you aren't skilled enough for it, please don't fret!
 - Go to lecture, ask questions, go to office hours.

## Self reflection from student feedback

 - This was an absolutely fantastic time! Love teaching and the students. It really taught me the perspective and the hard work that professors put in everyday to make their content / work for their students
 - As some students said, reorganizing the lecture slides would also be my major critical point. Because I was maing things in a quick manner, I was not really having the foresight of really planning everything out and maing things really coherent.
    - One of the most confusing things is the ADC which is a very complicated system and I feel like I should have imrpvoed this
    - Probably should have hammered the beginner GPIO information at the beginning a bit more
    - Really look holistically at everything now that all the material and then reorganize it all into a proper set of slide decks
 - This has been a recuring problem with me that I know about, but is hard to really realize but I speak pretty fast and so during lectures that can be a problem.
 - Less text!!! (Tried my best there, but I like putting text on slides lol, makes it "easier" to follow, but also harder to follow since you can just read from the slides)
   - Be able to generate more picture, animations, websites would of course be better!
 - For some lectures they were really heavy on the video only content, where I just showed a couple of video during the whole lecture instead of teaching it, this was recieved with mixed feeling, some people like it and some thought it was a waste of lecture time (the problem is that if you assigned it / recommended people ot watch it they probably would not lol, so always a double edge sword)
 - One of the lectures, I forget which one but had the transformation matrix be wrong that was in code and I forget which one it was. However, it needs to be fixed (it was some kind of LiDAR cooridnate transformation where the y value was wrong since it just never got used)
 - Probably should add more incentive to attend lectures, maybe quiz but if that is the case then Zoom has to be an option
 - Give more clarity to students to be able to see their current checklist progress on the different assignements / have a script that automatically uploads the current assignmeent progress for the different labs and such
