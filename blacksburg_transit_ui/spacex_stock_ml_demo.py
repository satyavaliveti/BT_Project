from urllib.request import urlopen
import xml.etree.ElementTree as ET

from sklearn.linear_model import LogisticRegression


BT_ROUTES_URL = "https://www.bt4uclassic.org/webservices/bt4u_webservice.asmx/GetCurrentRoutes"


def get_realtime_info_percent():
    """
    Reads RealTimeInfoAvailable from the Blacksburg Transit route API.

    This value is useful for transit data, but it is not actually related to
    SpaceX stock or valuation. It is included here only because the demo was
    requested to use RealTimeInfoAvailable as an ML feature.
    """
    with urlopen(BT_ROUTES_URL, timeout=15) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)
    routes = root.findall("CurrentRoutes")

    if not routes:
        return 0.0

    realtime_routes = 0

    for route in routes:
        realtime_field = route.find("RealTimeInfoAvail")
        if realtime_field is not None and realtime_field.text == "true":
            realtime_routes += 1

    return realtime_routes / len(routes)


def train_demo_model():
    """
    Trains a tiny toy model.

    SpaceX is a private company, so there is no public SpaceX stock ticker.
    These rows are made-up example data for learning how ML classification works.

    Features:
    1. realtime_info_percent
    2. launch_success_rate
    3. positive_news_score

    Target:
    1 means "hypothetical value increased"
    0 means "hypothetical value did not increase"
    """
    training_features = [
        [0.60, 0.70, 0.40],
        [0.70, 0.80, 0.50],
        [0.80, 0.90, 0.80],
        [0.90, 0.95, 0.90],
        [0.40, 0.60, 0.30],
        [0.50, 0.55, 0.20],
        [0.75, 0.85, 0.70],
        [0.30, 0.50, 0.25],
    ]

    training_labels = [0, 1, 1, 1, 0, 0, 1, 0]

    model = LogisticRegression()
    model.fit(training_features, training_labels)
    return model


def main():
    realtime_info_percent = get_realtime_info_percent()
    model = train_demo_model()

    # Example values you can change.
    launch_success_rate = 0.90
    positive_news_score = 0.75

    example = [[realtime_info_percent, launch_success_rate, positive_news_score]]

    prediction = model.predict(example)[0]
    probability = model.predict_proba(example)[0][1]

    print("Important note:")
    print("SpaceX is private, so this is not a real stock prediction.")
    print("RealTimeInfoAvailable is transit data, not a financial indicator.")
    print()
    print(f"RealTimeInfoAvailable percent from BT API: {realtime_info_percent:.2%}")
    print(f"Launch success rate used: {launch_success_rate:.2%}")
    print(f"Positive news score used: {positive_news_score:.2f}")
    print()

    if prediction == 1:
        print("Toy model prediction: hypothetical SpaceX value may increase.")
    else:
        print("Toy model prediction: hypothetical SpaceX value may not increase.")

    print(f"Toy model confidence for increase: {probability:.2%}")


if __name__ == "__main__":
    main()
