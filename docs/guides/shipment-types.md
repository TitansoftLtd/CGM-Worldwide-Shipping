# Other Shipment Types

For **Operations**, **Declaration** and **Transport** handling anything other than a straightforward sea import.

Most of this documentation describes **Sea Import**, because that is the bulk of the work and the only type with a full 23-step task plan. The types below run differently. Where a step is the same as sea import, this guide says so rather than repeating it.

| Type | Task template | Covered here |
|------|---------------|--------------|
| Sea Import | Sea Import Workflow | The rest of the documentation |
| Air Import | Air Import Workflow | [Air freight declaration](declaration-customs.md#air-freight-declaration) |
| Air Export | Air Export Workflow | Below |
| Sea Transit | Sea Transit Import Workflow | Below |
| Road Transit Import | Road Transit Inbound Workflow | Below |
| Road Transit Export | Road Transit Outbound Workflow | Below |

---

## Air Export

The shipment is going out, so the airline is chosen before anything else can be numbered - the air waybill only exists once the booking does.

1. **Documents from the client**: invoice and packing list, sometimes the COA.
2. **Establish the routing** from the origin and destination addresses.
3. **Compare rates** across airlines and pick one with a route that works.
4. **Selecting the airline generates the air waybill number.** Nothing downstream can be filed before this.
5. **Customs entry.**
6. **Deliver the package to the airport.**
7. **Export formalities**: customs, ground handling, and any other agency involved.
8. **Weigh and measure** to get the correct dimensions.
9. **Book and pay** freight and handling charges.
10. **Hand over to the airline** for airlifting.
11. **Monitor the departure** so you know when the flight has left.
12. **Manifest**, then to customs for the **COE**.

The order that catches people out is 3-4: on an import the transport document arrives from the client, but on an export the airline selection is what creates it.

---

## Road Transit (Uganda)

Cargo moving by road to a neighbouring country. The entry is processed on the **destination** side, and the truck cannot move until the **C2** is in hand.

1. **Loading from the warehouse.**
2. **Client provides** the invoice and packing list.
3. **Operations Manager applies** for the **Certificate of Conformity** and the **EAC certificate**.
4. **Declarant processes the Uganda entry**; Finance pays.
5. **Uganda releases the entry.**
6. **Transporter shares truck details.**
7. **Exit notes generated** from those details.
8. **C2 obtained** - the authorisation for the goods to move within the country.
9. **Load the trucks**, once the C2 is through.
10. **Track** Nairobi to the border, then to the warehouse.
11. **Electronic cargo monitoring devices** are fitted to the trucks.

Steps 6 to 8 are strictly ordered: no truck details means no exit note, and no exit note means no C2.

---

## Sea Transit

Sea freight passing through Kenya to or from a neighbouring country. Which side prepares the entry, and which side verifies, depends on the direction.

### Import transit

- **Kenya** prepares the entry.
- **Verification is done on the Kenyan side.**
- The normal pre-clearance permits apply, exactly as for a sea import.

### Export transit

- **Uganda** prepares the entry and the **UBS permit**.
- **Kenya** prepares the **COC** and the **EAC certificate**.
- **Verification and release happen on the Ugandan side.**

### Release and movement

Once released, both directions run the same way:

1. **Book with KPA** using the release order.
2. **Loading slips from KPA**, then create the **delivery note**.
3. **Delivery note goes to Uganda** so the exit note can be processed.
4. **C2 obtained**, and the trucks go en route.
5. **Monitor and track** to destination.

### Who provides what

| From the client | From CGM as agent |
|-----------------|-------------------|
| Invoice | COMESA / EAC certificate |
| Packing list | Exit note |
| COA | C2 |
| Bill of Lading | |

---

## Related guides

- [Operations](operations.md) - the sea import flow these are variations on
- [Declaration & Customs](declaration-customs.md) - including air freight declaration
- [Transport & Containers](transport-containers.md) - allocation, tracking and container return
