# Native modeling regression — 2026-10-28

Public synthetic fixture authorized by the user. Its URL is retained in the
local test artifacts and conversation, not embedded in the distributed plugin.

The fixture contains two instances of a 20 × 30 × 5 mm cuboid and a group.
Fixture construction/topology lookup used the existing REST tools; the tests below
used native editor messages. No production drone geometry was edited.

- Translation +25 mm X: saved and rendered transforms matched within 1e-6.
- Rotation +90° about world Z: native drag sign is clockwise; after converting
  the API's right-hand angle to the native sign, saved/rendered transforms matched.
- Group membership: native BeginEdit/SpecifyFeature/Commit removed the second
  occurrence, verified the returned queries, then restored both members and verified.
- Part Studio measurement of opposite faces JHK/JHG: minimum and parallel distance
  both 0.005 m. The two face areas summed to 0.0012 m². Explicit points separated
  by 0.005 m also returned 0.005 m.
- Assembly faces JHK/JHG with the first occurrence path: minimum distance 0.005 m,
  parallel distance 0.004999999999999999 m, and combined area 0.0012 m². Returned
  endpoints include the saved 25 mm translation, confirming assembly coordinates.
- Assembly explicit points returned no quantities; whole-body query returned error
  17. These unsupported query forms return measured=false. Use geometric entities.
- Element and document microversions differ in this fixture. Unit tests verify
  unrelated document revision changes pass the element guard while stale element
  changes fail. Camera tests verify no model revision is required, while target
  and connection checks remain enforced.

Source evidence: public Onshape assets `woolsthorpe.425850a465996ab70100.js` and
`serialize.f9ab8cad22d26f2b1836.js`. Constructors are selected from known build
profiles, without scanning/executing arbitrary modules.

Limitations: mate parameter editing shares the tested group transaction wrapper,
but a separate live mate-limit test has not been performed. Definition readback
is not proof of a valid solver outcome. Free-point and whole-body assembly queries are unsupported in this build;
face measurements work in both assemblies and Part Studios.
