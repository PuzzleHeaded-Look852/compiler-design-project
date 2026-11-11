# Lumen: Project Summary

**Course:** Compiler Design (BCSE307L)
**Team:** Sanjay Suresh (24BCE2685), Sugesh Kumar (24BCE2687), Noel Ninan (24BCE2737), Advaith Sivakumar (24BCE2715), Ajay Kumar (24BCE2721)

## What is Lumen?

Lumen is a small programming language where **every number carries its unit**, like metres, seconds, kilograms or rupees. We also built the **compiler** for it: the program that reads Lumen code, checks it, and runs it.

The compiler checks the units before the program runs. If the units don't make sense, it refuses to run the program and tells you why.

## Why did we build it?

In most programming languages, a number is just a number. The computer can't tell if `12.5` means metres, seconds or dollars. That has caused real disasters:

- **Mars Climate Orbiter (1999):** One team's software gave a number in pound-force seconds. Another team's software read it as newton-seconds. The two differ by a factor of 4.45. The spacecraft was lost, a $327.6 million mistake.
- **Gimli Glider (1983):** An Air Canada plane's crew used 1.77 (pounds per litre) where kilograms per litre was needed. They loaded less than half the fuel they needed. Both engines stopped in mid-air. The pilots glided to a safe landing, and nobody died.

In both cases the computer couldn't notice, because to it the number was just a number. **In Lumen, both mistakes are compile errors.**

## The idea in three steps

1. **The unit is part of the number.** `9.8 m/s^2` and `12.5 lbf*s` are different kinds of value, just as a word and a number are different kinds of value.
2. **The compiler does the physics.**
   - Adding needs the same kind of unit: `3 m + 2 s` is an error, but `1 km + 500 m` is fine and gives `1.5 km`.
   - Multiplying combines units: `3 m * 4 m = 12 m^2`.
   - Dividing combines or cancels them: `100 m / 20 s = 5 m/s`.
   - If the units are the same kind but a different size (km and m), the compiler converts automatically and exactly.
3. **Then the units are removed.** The program that actually runs is plain arithmetic, so the checking costs nothing while the program runs.

## What Lumen code looks like

```
unit h = 3600 s;                  // declare a unit: 1 hour = 3600 seconds

fn pace(d: km, t: min) -> km/h {  // a function whose inputs and output have units
    return d / t;
}

fn main() {
    let d = 42.195 km;            // a number followed by a unit
    let t = 3 h + 30 min;         // mixed units are converted exactly
    print(pace(d, t));            // prints 12.05571429 km/h
    print(d in m);                // "in" converts: prints 42195.0 m
}
```

The Mars bug in Lumen:

```
update_trajectory(12.5);          // ERROR: 12.5 of what unit?
update_trajectory(12.5 lbf*s);    // OK: converted to 55.6 N*s automatically
```

## How the compiler works

A compiler is a translator, and ours works like an assembly line with **seven stations**. Each one takes the previous station's output, does one job, and passes it on.

| # | Station | What it does |
|---|---------|--------------|
| 1 | **Lexer** | Breaks the text into words (called tokens) |
| 2 | **Parser** | Works out the structure and builds a tree, so it knows what happens first |
| 3 | **Unit checker** | Works out the unit of every expression and catches unit mistakes. This is the heart of the project |
| 4 | **IR (intermediate code)** | Rewrites the program as very simple one-step instructions |
| 5 | **Optimizer** | Does the easy calculations ahead of time, so the program is smaller |
| 6 | **Bytecode** | Writes the program as instructions for a small imaginary computer |
| 7 | **VM (virtual machine)** | Runs those instructions and prints the answer |

Stations 1 to 3 understand the program and its units. From station 4 onwards there are only plain numbers.

## One program through the whole line

```
unit h = 3600 s;
fn main() {
    let d = 90 km;
    let t = 1.5 h;
    let v = d / t;
    print(v);
    print(v in m/s);
}
```

| Station | What happens |
|---------|--------------|
| Lexer | Splits the text into tokens like `LET`, `d`, `=`, `90`, `km` |
| Parser | Builds a tree: `v = d / t` becomes a divide with `d` and `t` underneath |
| Unit checker | `d` is a length, `t` is a time, so `v` is a speed (km/h). `v in m/s` needs a conversion, so it adds one |
| IR | Simple steps, such as `t1 = d / t` and `t2 = v * 0.2777` for the conversion |
| Optimizer | Everything is a known constant, so it calculates the answers at compile time. 8 instructions become 3 |
| Bytecode | Just `PUSH 60.0`, `PRINT`, `PUSH 16.67`, `PRINT`, `RET` |
| VM | Prints `60.0 km/h` and `16.66666667 m/s` |

## Helpful error messages

When something is wrong, the compiler shows the line, points at the exact spot, and suggests a fix. It never shows a crash. For example:

```
error: argument 1 of 'update_trajectory': expected impulse (N*s), found a plain number
   13 |     update_trajectory(from_ground_file);
      |                       ^~~~~~~~~~~~~~~~~
      = help: write the literal with its unit (e.g. `4 N*s`)
```

## Why it is clever

- **Units are checked like maths.** Multiplying adds the unit exponents, dividing subtracts them, and adding needs them equal. This works for any unit, even ones you invent.
- **Conversions are exact.** We use exact fractions instead of rounded decimals, so km to m and back to km is exactly 1.
- **No cost at run time.** The checking happens once, at compile time. The running program has no unit logic at all.

## How we know it works

- 187 automated tests, all passing
- 34 example programs, each with a recorded correct output that the tests compare against
- Every example gives the same output with the optimizer on and off
- About 3,437 lines of Python, with no outside libraries
- A web playground where anyone can try the compiler in a browser

## Honest limits

- Lumen checks one program at a time. Mars crossed two programs, so Lumen catches the bug where a number enters a function with a declared unit, but it can't stop a person from deliberately writing the wrong unit.
- No Celsius or Fahrenheit, because temperatures have an offset that our conversions can't express.
- It tracks what a number measures, not what it means. Torque and energy have the same dimension, so Lumen can't tell them apart.
- It runs on a Python virtual machine, so it is not fast.

## How to try it

- **Easiest:** double-click `run_playground.command`. A web page opens. Pick an example, press Run, and click the tabs to see each station's output. The last item in the list is a blank editor for your own code.
- **Command line:**
  ```
  cd lumen-compiler
  export PYTHONPATH=src
  python -m lumen run examples/mars_bug.lum      # compile error
  python -m lumen run examples/mars_fixed.lum    # prints 55.60277019 N*s
  python -m pytest -q                            # 187 passed
  ```

## Who built what

| Person | Part |
|--------|------|
| Sanjay | Lexer, error messages, command line |
| Advaith | Parser and syntax tree |
| Sugesh | Unit system and unit checker |
| Noel | Intermediate code and optimizer |
| Ajay | Bytecode, virtual machine, tests and the web playground |
