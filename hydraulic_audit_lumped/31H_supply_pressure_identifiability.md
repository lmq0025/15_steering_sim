# Supply-pressure identifiability

`R_eq=1.18e10 Pa s/m3` was identified from the C1 native pump-outlet pressure (18.6623 MPa), RV010 cracking pressure (16 MPa), and one-pump flow 0.000225 m3/s. It represents the algebraic pump-outlet-to-relief-path loss, not a pipe state and not valve-manifold pressure. IR V3 shows two parallel pumps per supply group and one pressure-control path per pump, so the runtime now applies the same per-pump branch law rather than doubling one full resistance.

The estimate uses the 1 s native baseline/peak measurement at `pout@pump01`; it is therefore a calibration target, not independent validation. The four pumps share geometry and measured native peak, so the value is applied symmetrically, but transfer to other pump speeds/openings is unverified. S1/S2 would have supplied the required holdout conditions; Amesim refused both temporary-signal runs, so transferability remains CONDITIONAL and no further adjustment was made.
