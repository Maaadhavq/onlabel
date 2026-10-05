"""Small hand-written SPL document and helpers shared by the tests (no network, no models)."""

from __future__ import annotations

import hashlib

import numpy as np

SPL = b"""<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="urn:hl7-org:v3">
  <setId root="11111111-2222-3333-4444-555555555555"/>
  <versionNumber value="7"/>
  <effectiveTime value="20260618"/>
  <subject><manufacturedProduct><manufacturedProduct>
    <name>Testadrug</name>
    <asEntityWithGeneric><genericMedicine><name>testaglutide</name></genericMedicine></asEntityWithGeneric>
  </manufacturedProduct></manufacturedProduct></subject>
  <component><structuredBody>
    <component><section><code code="48780-1"/><text><paragraph>product data</paragraph></text></section></component>
    <component><section>
      <code code="34066-1"/><title>WARNING: RISK OF THYROID C-CELL TUMORS</title>
      <text><list><item><caption>&#8226;</caption><paragraph>Testadrug causes thyroid C&#8209;cell tumors in rodents.</paragraph></item></list></text>
    </section></component>
    <component><section>
      <code code="34067-9"/><title>1 INDICATIONS AND USAGE</title>
      <text>
        <paragraph>TESTADRUG is indicated in combination with a reduced calorie diet:</paragraph>
        <list listType="unordered">
          <item><caption>&#8226;</caption><content>to reduce excess body weight in:</content>
            <list listType="unordered">
              <item><caption>o</caption><content>adults and pediatric patients aged 12 years and older with obesity.</content></item>
            </list>
          </item>
        </list>
      </text>
    </section></component>
    <component><section>
      <code code="34092-7"/><title>14 CLINICAL STUDIES</title>
      <component><section>
        <code code="42229-5"/><title>14.2 Weight Reduction Studies</title>
        <text>
          <paragraph>Table 8. Changes in Body Weight at Week 68</paragraph>
          <table>
            <thead><tr><th/><th>Placebo N=655</th><th>TESTADRUG N=1,306</th></tr></thead>
            <tbody>
              <tr><td>% change from baseline<sup>a</sup></td><td>-2.4</td><td>&#8209;14.9</td></tr>
              <tr><td>Patients losing 5% or more</td><td>31.1</td><td>83.5</td></tr>
            </tbody>
          </table>
          <paragraph>Units: 10<sup>9</sup>/L.</paragraph>
        </text>
      </section></component>
    </section></component>
    <component><section><code code="51945-4"/><title>PACKAGE LABEL</title><text><paragraph>carton</paragraph></text></section></component>
  </structuredBody></component>
</document>
"""


class HashEncoder:
    """Deterministic bag-of-words embedding: enough to exercise ranking and fusion code."""

    dim = 64

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in text.lower().split():
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def encode_query(self, query: str) -> np.ndarray:
        return self._vec(query)
