# N-Body Angular Momentum

An interactive 3D simulation of 1–15 bodies that interact only through mutual gravity. Made for PHY2060 (Lecture 13) to show that total linear momentum **P** and total angular momentum **L** about any fixed point O stay constant when there is no external force.

Live: https://sgnoohc.github.io/monet/nbody_simulation/

## What it shows

- Position vectors r_i from O, velocities v_i, net forces F_i and each pair force F_ij
- Total **L** drawn at O and total **P** drawn at the center of mass
- Each body's own L_i, drawn tip-to-tail from O (the chain ends at L) or at each body
- Charts: L_x, L_y, L_z about O over time (flat), and each body's share of L (changes while the sum stays flat)
- Live readouts: net torque about O stays near 10⁻¹⁵ while individual torques are of order 1
- A uniform external field you can switch on to see L and P change, dL/dt = M(R_cm − r_O) × g
- A 2D (planar) mode: bodies move in the x–y plane and L points along z

## Notes

- Kick-drift-kick leapfrog integrator. With central pair forces each step conserves L and P exactly, up to rounding error.
- Gravity is softened at short range (ε = 0.35) to keep close passes stable. The force still acts along the line between the two bodies, so the conservation argument is unchanged.
- One self-contained `index.html`. three.js r128 loads from jsDelivr.
