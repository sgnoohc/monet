# Physics Simulations

Interactive browser demonstrations for PHY2060. Each page is a single self-contained HTML file.

Index: https://sgnoohc.github.io/monet/physics_simulation/

| Page | What it shows |
|---|---|
| `nbody.html` | N-body gravity: conservation of P and L |
| `rigid_body.html` | Rigid body rotation: I = Σ dm r⊥², L = Iω |
| `waves.html` | Transverse and longitudinal waves side by side |

The old `/nbody_simulation/` links redirect here.

## N-Body Angular Momentum (`nbody.html`)

An interactive 3D simulation of 1–15 bodies that interact only through mutual gravity. Made for PHY2060 (Lecture 13) to show that total linear momentum **P** and total angular momentum **L** about any fixed point O stay constant when there is no external force.

Live: https://sgnoohc.github.io/monet/physics_simulation/nbody.html

## What it shows

- Position vectors r_i from O, velocities v_i, net forces F_i and each pair force F_ij
- Total **L** drawn at O and total **P** drawn at the center of mass
- Each body's own L_i, drawn tip-to-tail from O (the chain ends at L) or at each body
- Charts: L_x, L_y, L_z about O over time (flat), and each body's share of L (changes while the sum stays flat)
- Live readouts: net torque about O stays near 10⁻¹⁵ while individual torques are of order 1
- A uniform external field you can switch on to see L and P change, dL/dt = M(R_cm − r_O) × g
- An animated 3D right hand for the selected body: fingers along r, curling toward v (or F), thumb giving L_i = r × p (or τ_i = r × F)
- A 2D (planar) mode: bodies move in the x–y plane and L points along z

## Notes

- Kick-drift-kick leapfrog integrator. With central pair forces each step conserves L and P exactly, up to rounding error.
- Gravity is softened at short range (ε = 0.35) to keep close passes stable. The force still acts along the line between the two bodies, so the conservation argument is unchanged.
- One self-contained `nbody.html`. three.js r128 loads from jsDelivr.

## Rigid Body Rotation (`rigid_body.html`)

Live: https://sgnoohc.github.io/monet/physics_simulation/rigid_body.html

A rigid body built from small pieces dm spins about a vertical axis through O. Click a piece to see its r, r⊥, v = ω × r, a, F = dm a, p, L_i = r × p and τ_i = r × F. Each clicked piece is added to a running table of dm r⊥², which builds up I = Σ dm r⊥² until L_z = I ω.

- Shapes: rectangular plate, disk, ring, rod, L-shaped plate, thick 3D block (L_i tilts off the axis; the tilts cancel in the sum)
- Move the axis off the center of mass to see the parallel-axis term M d²
- Coarse or fine pieces: the discrete sum approaches the continuum formula
- Apply a torque: each piece gets a tangential acceleration α r⊥ and Σ τ_i,z = I α

## Transverse and Longitudinal Waves (`waves.html`)

Live: https://sgnoohc.github.io/monet/physics_simulation/waves.html

Choose **Transverse**, **Longitudinal**, or **Both**. All views use the same displacement s(x, t):

- Transverse: 32 beads on a string moving up and down
- Longitudinal: one row of 32 particles moving left and right, shaded where they bunch up, with compressions (C) and rarefactions (R) labeled

Click a particle to follow it (red). It only oscillates about its own spot while the wave moves on.

- Sine wave or single pulse, moving left or right; sliders for A, λ and f, with v = fλ and T shown
- Step ⅛ T at a time
- Off by default: the wavelength bracket, velocity arrows on every particle, and a graph of s against x with the density curve, which peaks at the compressions
- Vertical displacement is drawn up to 3× the horizontal scale so the transverse wave is easy to see
- Amplitude is capped so kA < 1, so neighbouring particles never pass each other
