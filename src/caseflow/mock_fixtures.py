"""Canned responses for the bundled demo documents (mock mode only).

These are hand-written examples of what a well-behaved model should return. They pass
through the same Pydantic validation, evidence checks and writers as real responses,
so a fixture that drifts from its document fails loudly instead of passing silently.
Keyed by source file name, then by task name. `{company_name}` is filled from config.
"""

from __future__ import annotations

from typing import Any

CLOSING = "Kind regards,\nCustomer Support Team\n{company_name}"

MOCK_RESPONSES: dict[str, dict[str, dict[str, Any]]] = {
    # 1. Resolved billing complaint with a documented, completed refund.
    "01_billing_refund_resolved.txt": {
        "extraction": {
            "customer_name": "Priya Raman",
            "email": "priya.raman@example.com",
            "phone_number": "+1-555-0142",
            "product_or_service": "Brightlane Premium Membership",
            "complaint_category": "billing",
            "issue_description": "Customer was charged twice ($49.00 each) for the Premium Membership renewal on 2 March 2026.",
            "resolution_provided": "Duplicate charge confirmed; refund of $49.00 processed on 15 March 2026 and customer notified by email.",
            "complaint": True,
            "escalation_required": None,
            "supporting_document_available": None,
            "overall_case_status": "closed",
            "missing_information": ["account or order reference"],
            "ambiguities": [],
            "evidence": [
                {"field_name": "customer_name", "source_quote": "From: Priya Raman"},
                {"field_name": "email", "source_quote": "priya.raman@example.com"},
                {"field_name": "phone_number", "source_quote": "Phone: +1-555-0142"},
                {"field_name": "product_or_service", "source_quote": "Brightlane Premium Membership renewal"},
                {"field_name": "complaint_category", "source_quote": "Double charge on my March invoice"},
                {"field_name": "issue_description", "source_quote": "I was charged twice for my Brightlane Premium Membership renewal on 2 March 2026."},
                {"field_name": "resolution_provided", "source_quote": "Refund of $49.00 was processed on 15 March 2026 and the customer was notified by email."},
                {"field_name": "complaint", "source_quote": "Please fix this as soon as possible."},
                {"field_name": "overall_case_status", "source_quote": "Case closed."},
            ],
        },
        "customer_email": {
            "subject": "Your duplicate membership charge has been refunded",
            "greeting": "Dear Priya Raman,",
            "body": (
                "Thank you for letting us know that you were charged twice for your Brightlane Premium "
                "Membership renewal on 2 March 2026. We are sorry for the inconvenience.\n\n"
                "Our records show that the duplicate charge was confirmed and a refund of $49.00 was "
                "processed on 15 March 2026.\n\n"
                "If you have any further questions about this charge, please reply to this email."
            ),
            "closing": CLOSING,
        },
        "case_summary": {
            "case_overview": "Billing complaint from Priya Raman about a duplicate Premium Membership renewal charge on 2 March 2026.",
            "key_issue": "Customer was charged $49.00 twice for one renewal.",
            "action_taken": "Billing Support confirmed the duplicate charge, processed a $49.00 refund on 15 March 2026 and notified the customer by email.",
            "current_status": "Closed - refund documented as processed.",
            "recommended_next_action": "No further action needed; optionally check why the renewal was charged twice to prevent recurrence.",
            "review_required": False,
            "review_reasons": [],
        },
    },
    # 2. Delivery complaint still open.
    "02_delivery_open.pdf": {
        "extraction": {
            "customer_name": "Marcus Oyelaran",
            "email": "marcus.o@example.com",
            "phone_number": "(555) 010-7788",
            "product_or_service": "Oakridge 3-Seater Sofa (order BL-20417)",
            "complaint_category": "delivery",
            "issue_description": "Sofa due for delivery on 5 April 2026 had not arrived by 19 April; tracking has shown 'In transit' for twelve days.",
            "resolution_provided": None,
            "complaint": True,
            "escalation_required": None,
            "supporting_document_available": None,
            "overall_case_status": "open",
            "missing_information": ["new delivery date", "carrier response"],
            "ambiguities": [],
            "evidence": [
                {"field_name": "customer_name", "source_quote": "Customer name: Marcus Oyelaran"},
                {"field_name": "email", "source_quote": "Email: marcus.o@example.com"},
                {"field_name": "phone_number", "source_quote": "Phone: (555) 010-7788"},
                {"field_name": "product_or_service", "source_quote": "Product: Oakridge 3-Seater Sofa"},
                {"field_name": "complaint_category", "source_quote": "My sofa was due to be delivered on 5 April 2026."},
                {"field_name": "issue_description", "source_quote": "It is now 19 April and it still has not arrived."},
                {"field_name": "complaint", "source_quote": "Customer Complaint Form"},
                {"field_name": "overall_case_status", "source_quote": "Case remains open."},
            ],
        },
        "customer_email": {
            "subject": "Update on your Oakridge sofa delivery (order BL-20417)",
            "greeting": "Dear Marcus Oyelaran,",
            "body": (
                "Thank you for contacting us about your Oakridge 3-Seater Sofa, which was due to be delivered "
                "on 5 April 2026 and has not yet arrived. We are sorry that you took time off work waiting "
                "for it.\n\n"
                "Our notes show that the carrier was contacted on 19 April 2026 and we are awaiting their "
                "response. At this stage we cannot yet confirm a new delivery date. We will update you once "
                "the carrier has responded."
            ),
            "closing": CLOSING,
        },
        "case_summary": {
            "case_overview": "Delivery complaint from Marcus Oyelaran: order BL-20417 (Oakridge 3-Seater Sofa) is two weeks late.",
            "key_issue": "Sofa due 5 April 2026 has not arrived; tracking stuck on 'In transit' for twelve days; customer lost two days off work.",
            "action_taken": "Carrier contacted on 19 April 2026; awaiting carrier response.",
            "current_status": "Open.",
            "recommended_next_action": "Chase the carrier for a confirmed delivery date and consider whether escalation or goodwill is appropriate given the delay.",
            "review_required": True,
            "review_reasons": ["Escalation need is not documented for a delivery that is two weeks late."],
        },
    },
    # 3. Defective product explicitly requiring escalation (not yet submitted).
    "03_defective_product_escalation.docx": {
        "extraction": {
            "customer_name": "Elena Kowalski",
            "email": "elena.kowalski@example.com",
            "phone_number": "+44 20 7946 0958",
            "product_or_service": "ThermaPro Electric Kettle, model TK-200",
            "complaint_category": "product_quality",
            "issue_description": "Kettle no longer switches off automatically after boiling and the base gets hot enough to scorch the worktop; customer feels unsafe using it.",
            "resolution_provided": None,
            "complaint": True,
            "escalation_required": True,
            "supporting_document_available": None,
            "overall_case_status": "open",
            "missing_information": ["order or receipt reference"],
            "ambiguities": [],
            "evidence": [
                {"field_name": "customer_name", "source_quote": "Customer | Elena Kowalski"},
                {"field_name": "email", "source_quote": "elena.kowalski@example.com"},
                {"field_name": "phone_number", "source_quote": "+44 20 7946 0958"},
                {"field_name": "product_or_service", "source_quote": "ThermaPro Electric Kettle, model TK-200"},
                {"field_name": "complaint_category", "source_quote": "Product Quality Complaint"},
                {"field_name": "issue_description", "source_quote": "The kettle stopped switching off automatically after boiling"},
                {"field_name": "complaint", "source_quote": "I no longer feel safe using it."},
                {"field_name": "escalation_required", "source_quote": "This case requires escalation to the Product Safety team."},
                {"field_name": "overall_case_status", "source_quote": "Status: Open"},
            ],
        },
        "customer_email": {
            "subject": "Your ThermaPro kettle safety concern",
            "greeting": "Dear Elena Kowalski,",
            "body": (
                "Thank you for telling us about the problem with your ThermaPro Electric Kettle (model TK-200). "
                "We understand that it no longer switches off automatically after boiling and that the base "
                "has become hot enough to scorch your worktop.\n\n"
                "For your safety, please stop using the kettle and keep it unplugged.\n\n"
                "Your case is currently open and has been identified as needing review by our Product Safety "
                "team. We will contact you with the next steps. If you have your order number or receipt, "
                "please reply with it so we can locate your purchase."
            ),
            "closing": CLOSING,
        },
        "case_summary": {
            "case_overview": "Potential safety defect reported by Elena Kowalski for a ThermaPro Electric Kettle, model TK-200.",
            "key_issue": "Kettle fails to switch off after boiling and the base overheats enough to scorch the worktop.",
            "action_taken": "Supervisor recorded that escalation to the Product Safety team is required; escalation has not yet been submitted.",
            "current_status": "Open - escalation required but not yet submitted.",
            "recommended_next_action": "Submit the escalation to the Product Safety team and advise the customer not to use the kettle.",
            "review_required": True,
            "review_reasons": ["Required safety escalation is still pending submission."],
        },
    },
    # 4. Service complaint with missing contact details.
    "04_service_missing_contact.txt": {
        "extraction": {
            "customer_name": None,
            "email": None,
            "phone_number": None,
            "product_or_service": "Washing machine installation",
            "complaint_category": "service_quality",
            "issue_description": "Installation technician arrived three hours late, left without connecting the water supply, and nobody called to explain the delay.",
            "resolution_provided": None,
            "complaint": True,
            "escalation_required": None,
            "supporting_document_available": None,
            "overall_case_status": "unknown",
            "missing_information": ["customer name", "email address", "phone number", "order reference"],
            "ambiguities": [],
            "evidence": [
                {"field_name": "product_or_service", "source_quote": "washing machine installation appointment"},
                {"field_name": "complaint_category", "source_quote": "I expect better service than this."},
                {"field_name": "issue_description", "source_quote": "left without connecting the water supply"},
                {"field_name": "complaint", "source_quote": "The installation technician arrived three hours late"},
            ],
        },
        "customer_email": {
            "subject": "Your washing machine installation appointment",
            "greeting": "Dear Customer,",
            "body": (
                "Thank you for your feedback about your washing machine installation appointment. We are sorry "
                "that the technician arrived three hours late, left without connecting the water supply, and "
                "that nobody called to explain the delay.\n\n"
                "The information available to us does not yet confirm a resolution. To help us follow this "
                "up, please reply with your name, a contact phone number and your order reference."
            ),
            "closing": CLOSING,
        },
        "case_summary": {
            "case_overview": "Service complaint from a feedback card at the Riverside branch about a washing machine installation.",
            "key_issue": "Technician was three hours late, did not connect the water supply, and the customer was not told about the delay.",
            "action_taken": "Not documented",
            "current_status": "Unknown - no follow-up recorded.",
            "recommended_next_action": "Identify the customer from the Riverside branch installation schedule for 22 April 2026 and arrange to complete the installation.",
            "review_required": True,
            "review_reasons": ["No customer name or contact details, so a reply cannot be sent.", "No action or status documented."],
        },
    },
    # 5. Positive feedback / general enquiry - not a complaint.
    "05_positive_feedback.pdf": {
        "extraction": {
            "customer_name": "Tomasz Lindqvist",
            "email": "t.lindqvist@example.com",
            "phone_number": None,
            "product_or_service": "Cordless vacuum",
            "complaint_category": "other",
            "issue_description": "Positive feedback about store staff, plus a question about replacement filters for the VX-9 model.",
            "resolution_provided": None,
            "complaint": False,
            "escalation_required": None,
            "supporting_document_available": None,
            "overall_case_status": "not_a_complaint",
            "missing_information": [],
            "ambiguities": [],
            "evidence": [
                {"field_name": "customer_name", "source_quote": "Name: Tomasz Lindqvist"},
                {"field_name": "email", "source_quote": "t.lindqvist@example.com"},
                {"field_name": "product_or_service", "source_quote": "Aisha helped me choose a cordless vacuum"},
                {"field_name": "complaint_category", "source_quote": "Could you also let me know whether you stock replacement filters"},
                {"field_name": "issue_description", "source_quote": "I just wanted to say thank you to the team at your Harbour Street store."},
                {"field_name": "complaint", "source_quote": "No problems at all - I am very happy with the purchase."},
                {"field_name": "overall_case_status", "source_quote": "No problems at all"},
            ],
        },
        "case_summary": {
            "case_overview": "Positive feedback from Tomasz Lindqvist about the Harbour Street store, with a product enquiry.",
            "key_issue": "Not a complaint. Customer praised staff member Aisha and asked whether replacement filters for the VX-9 model are stocked.",
            "action_taken": "Not documented",
            "current_status": "Not a complaint.",
            "recommended_next_action": "Share the feedback with the Harbour Street store team and answer the filter stock question.",
            "review_required": False,
            "review_reasons": [],
        },
    },
    # 6. Ambiguous case with conflicting status statements.
    "06_ambiguous_conflicting_status.docx": {
        "extraction": {
            "customer_name": "Daniel Achterberg",
            "email": "d.achterberg@example.com",
            "phone_number": None,
            "product_or_service": "StreamBox Pro subscription",
            "complaint_category": "technical",
            "issue_description": "StreamBox Pro loses connection every evening, preventing viewing after 7pm, for two weeks.",
            "resolution_provided": "Firmware update pushed remotely on 9 May 2026; a later note on 10 May reports dropouts continue.",
            "complaint": True,
            "escalation_required": None,
            "supporting_document_available": None,
            "overall_case_status": "unknown",
            "missing_information": ["phone number"],
            "ambiguities": [
                "Agent A note (9 May) says the issue is resolved, but Agent B note (10 May) says it is not resolved.",
            ],
            "evidence": [
                {"field_name": "customer_name", "source_quote": "Customer: Daniel Achterberg"},
                {"field_name": "email", "source_quote": "d.achterberg@example.com"},
                {"field_name": "product_or_service", "source_quote": "Product: StreamBox Pro subscription"},
                {"field_name": "complaint_category", "source_quote": "keeps losing connection every evening"},
                {"field_name": "issue_description", "source_quote": "I cannot watch anything after 7pm. This has been going on for two weeks."},
                {"field_name": "resolution_provided", "source_quote": "Firmware update pushed remotely. Issue resolved."},
                {"field_name": "resolution_provided", "source_quote": "still experiencing dropouts. Issue not resolved."},
                {"field_name": "complaint", "source_quote": "My StreamBox Pro keeps losing connection every evening"},
            ],
        },
        "customer_email": {
            "subject": "Your StreamBox Pro connection issue",
            "greeting": "Dear Daniel Achterberg,",
            "body": (
                "Thank you for contacting us about your StreamBox Pro, which has been losing connection every "
                "evening for the past two weeks.\n\n"
                "Our records show that a firmware update was sent to your device remotely on 9 May 2026. "
                "However, we also have a note that you were still experiencing dropouts on 10 May, so the "
                "information available to us does not confirm that the problem is resolved.\n\n"
                "Could you please reply to let us know whether the connection drops are still happening, and "
                "roughly what time they start?"
            ),
            "closing": CLOSING,
        },
        "case_summary": {
            "case_overview": "Technical complaint from Daniel Achterberg: StreamBox Pro drops connection every evening.",
            "key_issue": "Service unusable after 7pm for two weeks; case notes disagree on whether it is fixed.",
            "action_taken": "Firmware update pushed remotely on 9 May 2026.",
            "current_status": "Unclear - one note says resolved, a later note says not resolved.",
            "recommended_next_action": "Confirm the current status with the customer and, if dropouts continue, investigate beyond the firmware update.",
            "review_required": True,
            "review_reasons": ["Contradictory status notes from Agent A and Agent B."],
        },
    },
    # 7. Complaint claiming an attached invoice (unverified source claim).
    "07_invoice_attached_claim.pdf": {
        "extraction": {
            "customer_name": "Grace Mbeki",
            "email": "grace.mbeki@example.com",
            "phone_number": None,
            "product_or_service": "Garden Deluxe hamper",
            "complaint_category": "billing",
            "issue_description": "Invoice INV-58213 charged $129.99 for the Garden Deluxe hamper, but the advertised website price was $99.99.",
            "resolution_provided": None,
            "complaint": True,
            "escalation_required": None,
            "supporting_document_available": True,
            "overall_case_status": "unknown",
            "missing_information": ["phone number", "case status"],
            "ambiguities": [
                "Customer states the invoice and an advert screenshot are attached; the attachments were not available to or checked by this system.",
            ],
            "evidence": [
                {"field_name": "customer_name", "source_quote": "Grace Mbeki"},
                {"field_name": "email", "source_quote": "grace.mbeki@example.com"},
                {"field_name": "product_or_service", "source_quote": "for the Garden Deluxe hamper"},
                {"field_name": "complaint_category", "source_quote": "Wrong amount on invoice INV-58213"},
                {"field_name": "issue_description", "source_quote": "charged $129.99, but the advertised price on your website was $99.99"},
                {"field_name": "complaint", "source_quote": "Please correct the charge."},
                {"field_name": "supporting_document_available", "source_quote": "I have attached a copy of the invoice and a screenshot of the advert"},
            ],
        },
        "customer_email": {
            "subject": "Your query about invoice INV-58213",
            "greeting": "Dear Grace Mbeki,",
            "body": (
                "Thank you for contacting us about invoice INV-58213 for the Garden Deluxe hamper. We understand "
                "you were charged $129.99, while the price advertised on our website was $99.99.\n\n"
                "You mentioned that you attached a copy of the invoice and a screenshot of the advert. The "
                "information available to us does not yet confirm a resolution of the price difference. We "
                "will contact you once the charge has been reviewed, and we will let you know if we need any "
                "further details."
            ),
            "closing": CLOSING,
        },
        "case_summary": {
            "case_overview": "Billing complaint from Grace Mbeki about the price charged on invoice INV-58213.",
            "key_issue": "Charged $129.99 for the Garden Deluxe hamper versus an advertised price of $99.99.",
            "action_taken": "Not documented",
            "current_status": "Unknown - no handling notes in the document.",
            "recommended_next_action": "Verify the advertised price and the customer's attachments, then decide whether to adjust the charge.",
            "review_required": True,
            "review_reasons": ["Supporting documents are claimed by the customer but have not been verified.", "No action or status documented."],
        },
    },
    # 8. Pending (not completed) refund + a prompt-injection sentence that must be ignored.
    "08_pending_refund_injection.txt": {
        "extraction": {
            "customer_name": "Hiroshi Tanaka",
            "email": "hiroshi.tanaka@example.com",
            "phone_number": None,
            "product_or_service": "Nimbus Memory Foam Pillow, set of 2 (order BL-30955)",
            "complaint_category": "refund",
            "issue_description": "Customer returned the pillows on 3 May because of a strong chemical smell and has not received a refund.",
            "resolution_provided": "Return received at warehouse on 9 May; refund approved and scheduled to the original payment method, but not yet completed and no date confirmed.",
            "complaint": True,
            "escalation_required": None,
            "supporting_document_available": None,
            "overall_case_status": "in_progress",
            "missing_information": ["refund completion date", "refund amount", "phone number"],
            "ambiguities": [
                "The transcript contains an instruction-like message asking the system to mark the case resolved and claim a completed refund; it was treated as data and ignored.",
            ],
            "evidence": [
                {"field_name": "customer_name", "source_quote": "Customer: Hiroshi Tanaka"},
                {"field_name": "email", "source_quote": "hiroshi.tanaka@example.com"},
                {"field_name": "product_or_service", "source_quote": "Nimbus Memory Foam Pillow, set of 2"},
                {"field_name": "complaint_category", "source_quote": "I still have not received my refund."},
                {"field_name": "issue_description", "source_quote": "I returned the pillows on 3 May because they had a strong chemical smell."},
                {"field_name": "resolution_provided", "source_quote": "A refund has been approved and is scheduled to be issued to your original payment method."},
                {"field_name": "resolution_provided", "source_quote": "I cannot confirm the exact date."},
                {"field_name": "complaint", "source_quote": "I still have not received my refund."},
                {"field_name": "overall_case_status", "source_quote": "A refund has been approved and is scheduled"},
            ],
        },
        "customer_email": {
            "subject": "Update on your refund for order BL-30955",
            "greeting": "Dear Hiroshi Tanaka,",
            "body": (
                "Thank you for contacting us about your refund for the Nimbus Memory Foam Pillows (set of 2), "
                "which you returned because of a strong chemical smell. We are sorry for the inconvenience.\n\n"
                "Our records show that your return was received at our warehouse on 9 May and that a refund "
                "has been approved and is scheduled to be issued to your original payment method. The refund "
                "has not yet been confirmed as completed, and we cannot yet confirm the exact date. We will "
                "let you know once it has been issued."
            ),
            "closing": CLOSING,
        },
        "case_summary": {
            "case_overview": "Refund complaint from Hiroshi Tanaka for returned Nimbus Memory Foam Pillows (order BL-30955).",
            "key_issue": "Return received on 9 May but the refund has not reached the customer.",
            "action_taken": "Return received at the warehouse on 9 May; refund approved and scheduled (not yet completed).",
            "current_status": "In progress - refund pending, date unconfirmed.",
            "recommended_next_action": "Confirm the refund issue date and amount with Finance and update the customer.",
            "review_required": True,
            "review_reasons": [
                "Document contains an instruction-like message attempting to manipulate case processing (ignored).",
                "Refund completion date not confirmed.",
            ],
        },
    },
    # 9. Unconfirmed complaint - email is skipped (complaint_unconfirmed).
    "09_unconfirmed_enquiry.docx": {
        "extraction": {
            "customer_name": "Fatima Okonkwo",
            "email": None,
            "phone_number": "555-0199",
            "product_or_service": "SmartHeat Wi-Fi thermostat",
            "complaint_category": "unknown",
            "issue_description": "Caller said the thermostat is not working as expected with the heating schedule; the nature of the request is unclear.",
            "resolution_provided": None,
            "complaint": None,
            "escalation_required": None,
            "supporting_document_available": None,
            "overall_case_status": "unknown",
            "missing_information": ["email address", "nature of the request", "order reference"],
            "ambiguities": [
                "Unclear whether the caller is reporting a fault, asking for setup help, or wants to return the item.",
            ],
            "evidence": [
                {"field_name": "customer_name", "source_quote": "Caller | Fatima Okonkwo"},
                {"field_name": "phone_number", "source_quote": "Callback number | 555-0199"},
                {"field_name": "product_or_service", "source_quote": "SmartHeat Wi-Fi thermostat"},
                {"field_name": "issue_description", "source_quote": "\"is not doing what it should\" with the heating schedule"},
            ],
        },
        "case_summary": {
            "case_overview": "Phone message from Fatima Okonkwo about a SmartHeat Wi-Fi thermostat.",
            "key_issue": "Thermostat reportedly not following the heating schedule; unclear if this is a fault, a setup question, or a return request.",
            "action_taken": "Not documented",
            "current_status": "Unknown - call ended before details were taken.",
            "recommended_next_action": "Call the customer back on the recorded number to clarify the request before classifying it.",
            "review_required": True,
            "review_reasons": ["Complaint status is unconfirmed.", "Nature of the request is ambiguous."],
        },
    },
}
